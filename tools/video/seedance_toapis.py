"""ToAPIs Seedance multimodal reference generation (NOT source-video editing).

Docs: https://docs.toapis.cn/docs/cn/api-reference/videos/seedance-2/generation
A durable submission marker prevents accidental duplicate paid submissions.
Use resume_generation after an interrupted run; never re-POST automatically.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from tools.base_tool import (BaseTool, Determinism, ExecutionMode, ResourceProfile,
                             RetryPolicy, ToolResult, ToolRuntime, ToolStability,
                             ToolStatus, ToolTier)

_API_BASES = ('https://toapis.com', 'https://toapis.cn')
_MODELS = ('seedance-2-mini', 'seedance-2-fast')


class ToapisSeedance(BaseTool):
    name = 'toapis_seedance'
    version = '0.1.0'
    provider = 'toapis'
    capability = 'video_generation'
    tier = ToolTier.GENERATE
    runtime = ToolRuntime.API
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    dependencies = ['env:TOAPIS_API_KEY']
    install_instructions = ('Set TOAPIS_API_KEY. Local references use the registered '
                            'Tencent COS uploader and require public-read URLs. Mainland China: '
                            'set TOAPIS_API_BASE=https://toapis.cn per the official quickstart.')
    agent_skills = ['seedance-identity-edit', 'seedance-2-0', 'ai-video-gen']
    capabilities = ['reference_to_video']
    supports = {'reference_to_video': True, 'reference_video': True,
                'reference_image': True, 'native_audio': True, 'aspect_ratio': True,
                'edit_video': False, 'strict_source_edit': False}
    best_for = ['Explicitly approved video-plus-image reference generation experiments']
    not_good_for = ['Pixel-exact source editing', 'Guaranteed identity or timing preservation']
    fallback_tools = []
    quality_score = 0.8
    retry_policy = RetryPolicy(max_retries=0)
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, disk_mb=1500, network_required=True)
    idempotency_key_fields = ['client_business_id', 'output_path']
    side_effects = ['Uploads local references', 'Submits one paid generation',
                    'Persists task state and downloads resulting video']
    user_visible_verification = ['Compare generated motion, text, face, hair, and clothing with source',
                                 'Inspect settled billing separately from estimates']
    input_schema = {'type': 'object', 'required': ['output_path'], 'properties': {
        'operation': {'type': 'string', 'enum': ['reference_to_video', 'resume_generation'], 'default': 'reference_to_video'},
        'model': {'type': 'string', 'enum': list(_MODELS), 'default': 'seedance-2-mini'},
        'prompt': {'type': 'string'},
        'reference_video_path': {'type': 'string'}, 'reference_video_url': {'type': 'string'},
        'reference_image_path': {'type': 'string'}, 'reference_image_url': {'type': 'string'},
        'duration': {'type': 'integer', 'minimum': -1, 'maximum': 15, 'default': 5,
                     'description': '4-15 seconds. 0 or -1 = auto duration for seedance-2-fast.'},
        'resolution': {'type': 'string', 'enum': ['480p', '720p'], 'default': '720p'},
        'aspect_ratio': {'type': 'string', 'default': '9:16'},
        'generate_audio': {'type': 'boolean', 'default': False},
        'client_business_id': {'type': 'string'}, 'project_id': {'type': 'string'},
        'output_path': {'type': 'string'}, 'poll_interval_seconds': {'type': 'number', 'default': 15},
        'timeout_seconds': {'type': 'integer', 'default': 1200}}}
    output_schema = {'type': 'object', 'properties': {'output_path': {'type': 'string'}, 'job_id': {'type': 'string'}}}

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if os.environ.get('TOAPIS_API_KEY', '').strip() else ToolStatus.UNAVAILABLE

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 300.0

    @staticmethod
    def _safe(value: Any, key: str) -> Any:
        text = json.dumps(value, ensure_ascii=False, default=str)
        if key:
            text = text.replace(key, '[REDACTED]')
        text = re.sub(r'(?i)Bearer\s+[^\s"\\]+', 'Bearer [REDACTED]', text)
        return json.loads(text)

    @staticmethod
    def _save(path: Path, value: Any) -> None:
        temp = path.with_suffix(path.suffix + '.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)

    @staticmethod
    def _json(response: Any) -> dict:
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f'ToAPIs HTTP {response.status_code}: non-JSON response') from exc
        if not isinstance(data, dict):
            raise RuntimeError('ToAPIs returned an unexpected response shape')
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f'ToAPIs HTTP {response.status_code}: {data.get("error", data)}')
        return data

    @staticmethod
    def _media(value: str, inputs: dict) -> str:
        if urlparse(value).scheme in ('https', 'http'):
            return value
        path = Path(value).expanduser()
        if not path.is_file():
            raise ValueError(f'Reference file not found: {path}')
        from tools.tool_registry import registry
        registry.ensure_discovered()
        tool = registry.get('tencent_cos_upload')
        if tool is None:
            raise RuntimeError('Tencent COS uploader is not registered')
        result = tool.execute({'local_path': str(path), 'project_id': inputs.get('project_id'),
                               'verify_public_read': True})
        if not result.success or not result.data.get('url'):
            raise RuntimeError(result.error or 'Media upload returned no URL')
        return result.data['url']

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        key = os.environ.get('TOAPIS_API_KEY', '').strip()
        if not key:
            return ToolResult(success=False, error='TOAPIS_API_KEY is not configured')
        start = time.monotonic()
        state: dict = {}
        state_path = None
        owns_state = False
        try:
            output_value = inputs.get('output_path')
            if not output_value:
                raise ValueError('Explicit output_path is required')
            base = (os.environ.get('TOAPIS_API_BASE') or 'https://toapis.com').strip().rstrip('/')
            if base not in _API_BASES:
                raise ValueError('TOAPIS_API_BASE must be an official HTTPS toapis.com or toapis.cn origin')
            endpoint = base + '/v1/videos/generations'
            output = Path(output_value)
            state_path = output.with_suffix('.task.json')
            operation = inputs.get('operation', 'reference_to_video')
            if operation not in ('reference_to_video', 'resume_generation'):
                raise ValueError('Only reference generation is supported; edit_video is not supported')
            import requests
            headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
            if operation == 'resume_generation':
                state = json.loads(state_path.read_text())
                owns_state = True
                identifier = state.get('id') or state.get('client_business_id')
                if not identifier:
                    raise ValueError('No persisted task or business ID to resume')
                state = self._safe(self._json(requests.get(
                    f'{endpoint}/{quote(str(identifier), safe="")}', headers=headers,
                    timeout=60, allow_redirects=False)), key)
            else:
                if state_path.exists() or output.exists():
                    raise ValueError('Existing attempt detected; use resume_generation, never resubmit automatically')
                model = inputs.get('model', 'seedance-2-mini')
                duration = float(inputs.get('duration', 5))
                if model not in _MODELS or not duration.is_integer():
                    raise ValueError('Mini/Fast model and an integer duration are required')
                duration_i = int(duration)
                auto_duration = duration_i in (-1, 0)
                if auto_duration and model == 'seedance-2-mini':
                    raise ValueError('Auto duration 0/-1 is not supported for seedance-2-mini')
                if not auto_duration and not 4 <= duration_i <= 15:
                    raise ValueError('Duration must be 4-15 seconds, or 0/-1 auto for seedance-2-fast')
                resolution = inputs.get('resolution', '720p')
                ratio = inputs.get('aspect_ratio', '9:16')
                if resolution not in ('480p', '720p') or ratio not in ('21:9', '16:9', '4:3', '1:1', '3:4', '9:16', 'adaptive'):
                    raise ValueError('Unsupported resolution or aspect ratio')
                prompt = str(inputs.get('prompt', '')).strip()
                video = inputs.get('reference_video_url') or inputs.get('reference_video_path')
                image = inputs.get('reference_image_url') or inputs.get('reference_image_path')
                if not prompt or not video or not image:
                    raise ValueError('This reference adapter requires prompt, reference video, and reference image')
                output.parent.mkdir(parents=True, exist_ok=True)
                # Resolve the video first; roles, rather than array order, bind modalities.
                upload_inputs = {**inputs, 'project_id': f"{inputs.get('project_id') or 'toapis'}/toapis-{uuid.uuid4().hex}"}
                video_url = self._media(str(video), upload_inputs)
                image_url = self._media(str(image), upload_inputs)
                business_id = str(inputs.get('client_business_id') or f'om-{uuid.uuid4().hex}')
                payload = {'model': model, 'client_business_id': business_id, 'prompt': prompt,
                           'duration': duration_i, 'resolution': resolution, 'aspect_ratio': ratio,
                           'generate_audio': bool(inputs.get('generate_audio', False)),
                           'video_with_roles': [{'url': video_url, 'role': 'reference_video'}],
                           'image_with_roles': [{'url': image_url, 'role': 'reference_image'}]}
                self._save(output.with_suffix('.request.json'), payload)
                state = {'client_business_id': business_id, 'status': 'submission_pending', 'model': model}
                # Exclusive creation guards overlapping submissions for the same output.
                with state_path.open('x', encoding='utf-8') as handle:
                    json.dump(state, handle)
                owns_state = True
                submitted = self._safe(self._json(requests.post(
                    endpoint, headers=headers, json=payload, timeout=90, allow_redirects=False)), key)
                state.update(submitted)
            self._save(state_path, state)
            deadline = time.monotonic() + max(1, int(inputs.get('timeout_seconds', 1200)))
            while state.get('status') != 'completed':
                if state.get('status') in ('failed', 'cancelled', 'canceled'):
                    raise RuntimeError(f'ToAPIs task failed: {state.get("error", state.get("status"))}')
                identifier = state.get('id') or state.get('client_business_id')
                if not identifier:
                    raise RuntimeError('Submission returned no task ID; do not resubmit')
                if time.monotonic() >= deadline:
                    raise TimeoutError('Polling timed out; task may still run. Resume using saved task state')
                time.sleep(max(0, float(inputs.get('poll_interval_seconds', 15))))
                latest = self._safe(self._json(requests.get(
                    f'{endpoint}/{quote(str(identifier), safe="")}', headers=headers,
                    timeout=60, allow_redirects=False)), key)
                state.update(latest)
                self._save(state_path, state)
            items = state.get('result', {}).get('data', [])
            url = items[0].get('url') if items else None
            if not url or urlparse(url).scheme != 'https':
                raise RuntimeError('Completed task has no HTTPS result URL')
            # Never send the API credential to media/CDN URLs.
            response = requests.get(url, timeout=300)
            if response.status_code != 200 or not response.content:
                raise RuntimeError(f'Video download failed (HTTP {response.status_code}); resume without generating again')
            output.write_bytes(response.content)
            from tools.video._shared import probe_output
            billing = state.get('billing') or {}
            cost = float(billing['cost_usd']) if billing.get('status') == 'settled' and billing.get('cost_usd') is not None else None
            return ToolResult(success=True, data={
                'provider': self.provider, 'model': state.get('model'), 'operation': 'reference_to_video',
                'job_id': state.get('id'), 'output_path': str(output), 'billing': billing,
                'actual_cost_usd': cost, 'usage': state.get('usage', {}),
                'task_state_path': str(state_path), **probe_output(output)},
                artifacts=[str(output), str(state_path)], cost_usd=cost or 0,
                duration_seconds=round(time.monotonic()-start, 2))
        except Exception as exc:
            error = self._safe(str(exc), key)
            if state_path is not None and owns_state:
                self._save(state_path, {**state, 'last_client_error': error})
            return ToolResult(success=False, error=error,
                              data={'job_id': state.get('id'), 'billing': state.get('billing', {}),
                                    'task_state_path': str(state_path) if state_path else None},
                              duration_seconds=round(time.monotonic()-start, 2))
