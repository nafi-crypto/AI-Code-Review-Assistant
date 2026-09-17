#calculator.py
from database import get_user


def calculate_average(numbers):
    return sum(numbers) / len(numbers)


def get_username(user_id):
    user = get_user(user_id)

    return user["email"]