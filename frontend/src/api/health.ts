export type Readiness = {
  status: "ready" | "not_ready";
  dependencies: { postgresql: "up" | "down" };
};

export async function getReadiness(signal: AbortSignal): Promise<Readiness> {
  const response = await fetch("/api/v1/health/ready", {
    signal,
    cache: "no-store",
    credentials: "same-origin",
  });
  if (response.status !== 200 && response.status !== 503) {
    throw new Error("Unexpected health response");
  }
  const body: unknown = await response.json();
  if (
    typeof body !== "object" ||
    body === null ||
    !("status" in body) ||
    !("dependencies" in body) ||
    typeof body.dependencies !== "object" ||
    body.dependencies === null ||
    !("postgresql" in body.dependencies) ||
    !(
      (response.status === 200 && body.status === "ready" && body.dependencies.postgresql === "up") ||
      (response.status === 503 && body.status === "not_ready" && body.dependencies.postgresql === "down")
    )
  ) {
    throw new Error("Invalid health response");
  }
  return body as Readiness;
}
