import json
import sys
from pathlib import Path

from tools.base_tool import ToolStatus
from tools.video.seedance_toapis import ToapisSeedance


class Response:
    def __init__(self, data=None, status=200, content=b'video'):
        self.data, self.status_code, self.content = data, status, content
    def json(self):
        return self.data


class Requests:
    def __init__(self, posts=(), gets=()):
        self.posts, self.gets = list(posts), list(gets)
        self.post_calls, self.get_calls = [], []
    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        response = self.posts.pop(0)
        if isinstance(response, Exception): raise response
        return response
    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.gets.pop(0)


def inputs(tmp_path):
    return {'prompt': 'Reference video motion and image identity', 'duration': 5,
            'reference_video_url': 'https://cdn.example/in.mp4',
            'reference_image_url': 'https://cdn.example/ref.png',
            'output_path': str(tmp_path/'out.mp4'), 'poll_interval_seconds': 0}


def install(monkeypatch, fake):
    monkeypatch.setenv('TOAPIS_API_KEY', 'private-test-token')
    monkeypatch.setitem(sys.modules, 'requests', fake)
    monkeypatch.setattr('tools.video._shared.probe_output', lambda _: {})


def test_contract(monkeypatch):
    monkeypatch.delenv('TOAPIS_API_KEY', raising=False)
    tool = ToapisSeedance()
    assert tool.get_status() == ToolStatus.UNAVAILABLE
    assert not tool.supports['edit_video']
    assert tool.capabilities == ['reference_to_video']
    assert tool.retry_policy.max_retries == 0


def test_roles_billing_and_download_no_key(monkeypatch, tmp_path):
    fake = Requests([Response({'id': 'task-1', 'status': 'queued'})], [
        Response({'id': 'task-1', 'status': 'completed', 'result': {'data': [{'url': 'https://cdn.example/out.mp4'}]},
                  'billing': {'status': 'settled', 'cost_usd': '0.12'}}), Response()])
    install(monkeypatch, fake)
    result = ToapisSeedance().execute(inputs(tmp_path))
    assert result.success, result.error
    payload = fake.post_calls[0][1]['json']
    assert payload['model'] == 'seedance-2-mini'
    assert payload['video_with_roles'][0]['role'] == 'reference_video'
    assert payload['image_with_roles'][0]['role'] == 'reference_image'
    assert payload['generate_audio'] is False
    assert 'omni_reference_task_type' not in payload
    assert 'headers' not in fake.get_calls[-1][1]
    assert result.data['actual_cost_usd'] == 0.12
    assert 'private-test-token' not in (tmp_path/'out.task.json').read_text()


def test_failed_task_preserves_id_no_retry(monkeypatch, tmp_path):
    fake = Requests([Response({'id': 'failed-1', 'status': 'failed', 'error': {'message': 'policy restriction'}})])
    install(monkeypatch, fake)
    result = ToapisSeedance().execute(inputs(tmp_path))
    assert not result.success and result.data['job_id'] == 'failed-1'
    assert len(fake.post_calls) == 1
    assert json.loads((tmp_path/'out.task.json').read_text())['id'] == 'failed-1'


def test_duplicate_attempt_refuses_post(monkeypatch, tmp_path):
    fake = Requests(); install(monkeypatch, fake)
    path = tmp_path/'out.task.json'; path.write_text('{"id":"old"}')
    result = ToapisSeedance().execute(inputs(tmp_path))
    assert not result.success and not fake.post_calls
    assert json.loads(path.read_text()) == {'id': 'old'}


def test_resume_download_never_posts(monkeypatch, tmp_path):
    fake = Requests(gets=[Response({'id': 'existing', 'status': 'completed', 'result': {'data': [{'url': 'https://cdn.example/out.mp4'}]}}), Response()])
    install(monkeypatch, fake)
    (tmp_path/'out.task.json').write_text('{"id":"existing"}')
    result = ToapisSeedance().execute({**inputs(tmp_path), 'operation': 'resume_generation'})
    assert result.success and not fake.post_calls
    assert result.data['actual_cost_usd'] is None


def test_redacts_key_and_preserves_ambiguous_submission(monkeypatch, tmp_path):
    fake = Requests([RuntimeError('private-test-token leaked')]); install(monkeypatch, fake)
    result = ToapisSeedance().execute(inputs(tmp_path))
    assert not result.success
    assert 'private-test-token' not in result.error
    state = (tmp_path/'out.task.json').read_text()
    assert 'private-test-token' not in state
    assert json.loads(state)['client_business_id']
    assert len(fake.post_calls) == 1


def test_invalid_fraction_or_edit_rejected(monkeypatch, tmp_path):
    fake = Requests(); install(monkeypatch, fake)
    for extra in [{'duration': 4.4}, {'operation': 'edit_video'}, {'model': 'unapproved'}]:
        result = ToapisSeedance().execute({**inputs(tmp_path), **extra})
        assert not result.success
    assert not fake.post_calls and not fake.get_calls


def test_official_mainland_base(monkeypatch, tmp_path):
    fake = Requests([Response({'id': 'cn-task', 'status': 'failed', 'error': 'test failure'})])
    install(monkeypatch, fake)
    monkeypatch.setenv('TOAPIS_API_BASE', 'https://toapis.cn')
    ToapisSeedance().execute(inputs(tmp_path))
    assert fake.post_calls[0][0] == 'https://toapis.cn/v1/videos/generations'


def test_unknown_api_origin_refused_before_sending_key(monkeypatch, tmp_path):
    fake = Requests(); install(monkeypatch, fake)
    monkeypatch.setenv('TOAPIS_API_BASE', 'https://other.example')
    result = ToapisSeedance().execute(inputs(tmp_path))
    assert not result.success and not fake.post_calls and not fake.get_calls


def test_video_upload_precedes_image_with_unique_namespace(monkeypatch, tmp_path):
    fake = Requests([Response({'id': 'one', 'status': 'failed', 'error': 'test'})])
    install(monkeypatch, fake)
    uploaded = []
    def media(value, params):
        uploaded.append((value, params['project_id']))
        return 'https://cdn.example/' + Path(value).name
    monkeypatch.setattr(ToapisSeedance, '_media', staticmethod(media))
    params = inputs(tmp_path)
    params.update({'reference_video_url': '', 'reference_image_url': '',
                   'reference_video_path': '/local/video.mp4', 'reference_image_path': '/local/ref.png',
                   'project_id': 'project'})
    ToapisSeedance().execute(params)
    assert [item[0] for item in uploaded] == ['/local/video.mp4', '/local/ref.png']
    assert uploaded[0][1] == uploaded[1][1]
    assert uploaded[0][1].startswith('project/toapis-')

def test_auto_duration_allowed_for_fast(monkeypatch, tmp_path):
    fake = Requests([Response({'id': 'auto-1', 'status': 'failed', 'error': 'test failure'})])
    install(monkeypatch, fake)
    result = ToapisSeedance().execute({**inputs(tmp_path), 'model': 'seedance-2-fast',
                                       'duration': -1, 'aspect_ratio': 'adaptive'})
    payload = fake.post_calls[0][1]['json']
    assert payload['duration'] == -1
    assert payload['aspect_ratio'] == 'adaptive'
    assert payload['model'] == 'seedance-2-fast'
    assert not result.success


def test_auto_duration_rejected_for_mini(monkeypatch, tmp_path):
    fake = Requests(); install(monkeypatch, fake)
    result = ToapisSeedance().execute({**inputs(tmp_path), 'model': 'seedance-2-mini', 'duration': -1})
    assert not result.success and not fake.post_calls

