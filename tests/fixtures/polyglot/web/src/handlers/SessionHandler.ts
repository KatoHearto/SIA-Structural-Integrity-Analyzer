export async function submitSession(req, res) {
    if (!req.body?.token) {
        throw new Error("token required");
    }

    const baseUrl = process.env.API_URL;
    const response = await fetch(`${baseUrl}/session`, { method: "POST" });
    return res.json(await response.json());
}
