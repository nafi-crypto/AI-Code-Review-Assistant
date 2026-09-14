tests = [

# 1. Undefined variable
{
    "name": "Undefined Variable",
    "language": "Python",
    "code": """
def calculate():
    return total + 10

print(calculate())
""",
    "expected": ["bug"]
},

# 2. Division by zero
{
    "name": "Division By Zero",
    "language": "Python",
    "code": """
def average(numbers):
    return sum(numbers) / len(numbers)

print(average([]))
""",
    "expected": ["error"]
},

# 3. Missing dictionary key
{
    "name": "Missing Dictionary Key",
    "language": "Python",
    "code": """
user = {
    "name": "Alice",
    "age": 21
}

print(user["email"])
""",
    "expected": ["error"]
},

# 4. SQL Injection
{
    "name": "SQL Injection",
    "language": "Python",
    "code": """
import sqlite3

username = input("Username: ")

connection = sqlite3.connect("users.db")
query = "SELECT * FROM users WHERE username = '" + username + "'"

connection.execute(query)
""",
    "expected": ["security"]
},

# 5. Command Injection
{
    "name": "Command Injection",
    "language": "Python",
    "code": """
import subprocess

command = input("Enter command: ")

subprocess.run(command, shell=True)
""",
    "expected": ["security"]
},

# 6. None handling
{
    "name": "None Handling",
    "language": "Python",
    "code": """
def get_name(user):
    return user["name"]

user = None

print(get_name(user).upper())
""",
    "expected": ["error"]
},

# 7. Performance
{
    "name": "Nested Loop Performance",
    "language": "Python",
    "code": """
def find_duplicates(items):
    duplicates = []

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i] == items[j]:
                duplicates.append(items[i])

    return duplicates
""",
    "expected": ["performance"]
},

# 8. Hardcoded secret
{
    "name": "Hardcoded API Key",
    "language": "Python",
    "code": """
API_KEY = "sk-test-123456789abcdef"

def connect():
    print(API_KEY)
""",
    "expected": ["security"]
},

# 9. Java runtime error
{
    "name": "Java Array Error",
    "language": "Java",
    "code": """
public class Main {
    public static void main(String[] args) {
        int[] numbers = {10, 20, 30};
        System.out.println(numbers[5]);
    }
}
""",
    "expected": ["bug", "error"]
},

# 10. C++ memory issue
{
    "name": "C++ Array Error",
    "language": "C++",
    "code": """
#include <iostream>
using namespace std;

int main() {
    int arr[3] = {1, 2, 3};

    cout << arr[10];

    return 0;
}
""",
    "expected": ["bug"]
}

]

print("Total benchmark tests:", len(tests))

for i, test in enumerate(tests, 1):
    print(f"{i}. {test['name']} - {test['language']} - Expected: {test['expected']}")