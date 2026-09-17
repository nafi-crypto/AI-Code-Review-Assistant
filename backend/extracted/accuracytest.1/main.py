#main.py
from calculator import calculate_average
from calculator import get_username
from security import run_command


def main():
    numbers = []

    average = calculate_average(numbers)

    username = get_username(1)

    command = input("Enter command: ")
    output = run_command(command)

    print(average)
    print(username)
    print(output)


if __name__ == "__main__":
    main()