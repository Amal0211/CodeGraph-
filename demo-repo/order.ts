import { User, validateUser } from './user';
import { quickCharge } from './payment';

export function createOrder(user: User, amount: number): boolean {
    if (!validateUser(user)) {
        throw new Error("Invalid user");
    }
    return quickCharge(amount);
}
