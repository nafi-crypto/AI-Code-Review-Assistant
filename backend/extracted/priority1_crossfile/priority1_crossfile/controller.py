#controller.py
from database import find_user
from utils import normalize_username

def handle_request(username):
    username = normalize_username(username)
    return find_user(username)