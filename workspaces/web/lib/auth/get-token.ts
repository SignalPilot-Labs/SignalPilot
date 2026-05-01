import "server-only";
import { auth } from "@clerk/nextjs/server";

export async function getCloudJwt(): Promise<string> {
  const { getToken } = await auth();
  const token = await getToken({ template: "workspaces" });
  if (!token) {
    throw new Error("AUTH_REQUIRED: no Clerk session");
  }
  return token;
}
