export interface User {
    id: string;
    name: string;
}

export function validateUser(user: User): boolean {
    return Boolean(user && user.id);
}
