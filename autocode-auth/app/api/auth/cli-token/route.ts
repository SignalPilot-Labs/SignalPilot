import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { randomBytes } from "crypto";

export async function POST() {
  const session = await auth();

  if (!session?.user?.id) {
    return NextResponse.json(
      { error: "UNAUTHORIZED" },
      { status: 401 }
    );
  }

  const token = randomBytes(32).toString("hex");
  const expiresAt = new Date(Date.now() + 10 * 60 * 1000); // 10 minutes

  await prisma.cliToken.create({
    data: {
      token,
      userId: session.user.id,
      expiresAt,
    },
  });

  return NextResponse.json({ token, expiresAt: expiresAt.toISOString() });
}

export async function GET() {
  // CLI polls this to check if browser auth is complete
  const session = await auth();

  if (!session?.user?.id) {
    return NextResponse.json({ authenticated: false });
  }

  return NextResponse.json({
    authenticated: true,
    user: {
      name: session.user.name,
      email: session.user.email,
      image: session.user.image,
    },
  });
}
