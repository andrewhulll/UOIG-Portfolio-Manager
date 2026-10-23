"""Anyone signed in can leave feedback; only admins read and resolve it."""
from tests.test_submissions import api  # noqa: F401  (fixture)


def test_feedback_submit_list_and_resolve(api):  # noqa: F811
    assert api.call('POST', '/feedback', user='a', body={'body': '  Add dark mode  ', 'page': '/stocks'}).status_code == 200
    assert api.call('POST', '/feedback', user='a', body={'body': '   '}).status_code == 422

    assert api.call('GET', '/feedback', user='a').status_code == 403
    listed = api.call('GET', '/feedback', user='admin').json()
    assert listed['open'] == 1 and listed['items'][0]['body'] == 'Add dark mode'
    fid = listed['items'][0]['id']

    assert api.call('PATCH', f'/feedback/{fid}', user='a', body={'resolved': True}).status_code == 403
    assert api.call('PATCH', f'/feedback/{fid}', user='admin', body={'resolved': True}).status_code == 200
    item = api.call('GET', '/feedback', user='admin').json()
    assert item['open'] == 0 and item['items'][0]['resolved_by'] == 'admin'

    api.call('PATCH', f'/feedback/{fid}', user='admin', body={'resolved': False})
    assert api.call('GET', '/feedback', user='admin').json()['open'] == 1
    assert api.call('PATCH', '/feedback/nope', user='admin', body={'resolved': True}).status_code == 404
