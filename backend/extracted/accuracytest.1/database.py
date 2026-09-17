#database.py
def get_user(user_id):
    users = {
        1: {"name": "Alice"}
    }

    return users.get(user_id)