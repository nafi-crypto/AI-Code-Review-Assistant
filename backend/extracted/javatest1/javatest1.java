import java.util.Scanner;

public class Main {

    static int calculateAverage(int[] numbers) {
        int sum = 0;

        for (int n : numbers) {
            sum += n;
        }

        return sum / numbers.length;
    }

    static void printElement(int[] numbers, int index) {
        System.out.println(numbers[index]);
    }

    public static void main(String[] args) {

        Scanner sc = new Scanner(System.in);

        int[] numbers = {10, 20, 30};

        System.out.println(calculateAverage(new int[]{}));

        int index = sc.nextInt();

        printElement(numbers, index);
    }
}