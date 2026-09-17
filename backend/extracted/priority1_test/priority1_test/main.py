#main.py
from auth import login
from database import get_user

username = input("Username: ")
password = input("Password: ")

if login(username, password):
    print(get_user(username))