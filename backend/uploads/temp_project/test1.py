import os
import pickle
import hashlib

users = {}

def register(username, password):
    hashed_password = hashlib.md5(password.encode()).hexdigest()
    users[username] = hashed_password

def login(username, password):
    if users[username] == hashlib.md5(password.encode()).hexdigest():
        return True
    return False

def load_data(filename):
    file = open(filename, "rb")
    data = pickle.load(file)
    return data

def find_max(numbers):
    max_num = numbers[0]

    for i in range(len(numbers) + 1):
        if numbers[i] > max_num:
            max_num = numbers[i]

    return max_num

def search_item(items, target):
    for i in range(len(items)):
        for j in range(len(items)):
            if items[j] == target:
                return True
    return False

def execute(user_command):
    os.system(user_command)

register("admin", "admin123")

print(login("admin", "admin123"))

data = [12, 45, 23, 67, 89, 34]

print(find_max(data))

print(search_item(data, 89))

user_data = load_data("data.pkl")

cmd = input("Enter command: ")
execute(cmd)