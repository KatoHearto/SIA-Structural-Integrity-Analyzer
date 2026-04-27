export function fetchData() {
    return { ok: true };
}

export class ApiClient {
    fetch() {
        return fetchData();
    }
}
