#include <iostream>
#include <vector>
using namespace std;

int findDuplicate(vector<int>& numbers) {

    for (int i = 0; i < numbers.size(); i++) {
        for (int j = i + 1; j < numbers.size(); j++) {
            if (numbers[i] == numbers[j]) {
                return numbers[i];
            }
        }
    }

    return -1;
}

int main() {

    int arr[3] = {10, 20, 30};

    cout << arr[10] << endl;

    vector<int> numbers = {1, 2, 3, 2};

    cout << findDuplicate(numbers) << endl;

    return 0;
}