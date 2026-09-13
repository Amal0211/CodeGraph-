export class PaymentService {
    chargeCard(amount: number): boolean {
        return amount > 0;
    }

    refundCard(txId: string): boolean {
        return true;
    }
}

export function quickCharge(amount: number): boolean {
    const ps = new PaymentService();
    return ps.chargeCard(amount);
}
