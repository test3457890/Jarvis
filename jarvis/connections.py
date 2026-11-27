"""Read-only inventory of Jarvis's built-in optional services."""
from . import secure

REVOCABLE = {
    'Canvas calendar feed': 'canvas_feed_url',
    'Brave public search': 'brave_search_key',
    'GitHub upload': 'github_upload_token',
    'SMTP email': 'smtp_password',
}


def status(cfg):
    internet = bool(cfg.get('allow_internet_tools'))
    canvas = secure.has_secret('canvas_feed_url')
    brave = secure.has_secret('brave_search_key')
    github = bool(cfg.get('github_upload_repo')) and secure.has_secret('github_upload_token')
    smtp = secure.has_secret('smtp_password') and bool(secure.get_secret('smtp_user'))
    local_image = bool(cfg.get('image_generation_url'))
    return [
        {'name':'Canvas calendar feed', 'state':'Configured' if canvas else 'Needs setup',
         'revocable': canvas, 'scope':'Read calendar feed on its sync schedule; Internet toggle does not pause Canvas',
         'setup':'python -m jarvis setup'},
        {'name':'Brave public search', 'state':('Ready' if internet and cfg.get('allow_web_search') else 'Paused') if brave else 'Needs setup',
         'revocable': brave,
         'scope':'Public query after approval; no personal files', 'setup':'python -m jarvis setup'},
        {'name':'GitHub upload', 'state':('Ready' if internet else 'Paused') if github else 'Needs setup',
         'revocable': github,
         'scope':'Approved upload to configured repository only; no issue or repository reading',
         'setup':'python -m jarvis setup'},
        {'name':'SMTP email', 'state':'Configured' if smtp else 'Needs setup',
         'revocable': smtp,
         'scope':'Send only after recipient, subject and body confirmation; the Internet toggle does not pause SMTP',
         'setup':'python -m jarvis setup'},
        {'name':'Project NOMAD', 'state':'Address set; not checked',
         'scope':'Read from configured local service when requested', 'setup':'python -m jarvis setup'},
        {'name':'Local image generation', 'state':'Address set; not checked' if local_image else 'Needs setup',
         'scope':'Send a prompt to configured local image endpoint when requested', 'setup':'python -m jarvis setup'},
    ]
