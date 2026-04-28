import { BaseShell } from "@/base";
import { ApiClient } from "@/infra";

export class AppShell extends BaseShell {
    private api;

    constructor() {
        super();
        this.api = new ApiClient();
    }

    render() {
        return this.load();
    }

    load() {
        super.render();
        return this.api.fetch();
    }
}
