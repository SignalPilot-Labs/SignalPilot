import { NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";
import { randomBytes, createHash } from "crypto";

function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export async function POST() {
  const session = await auth();

  if (!session?.user?.id) {
    return NextResponse.json(
      { error: "UNAUTHORIZED" },
      { status: 401 }
    );
  }

  const rawToken = randomBytes(32).toString("hex");
  const hashedToken = hashToken(rawToken);
  const expiresAt = new Date(Date.now() + 10 * 60 * 1000); // 10 minutes

  await prisma.$transaction(async (tx) => {
    // Clean up expired tokens
    await tx.cliToken.deleteMany({
      where: { expiresAt: { lt: new Date() } },
    });

    // Limit to 5 active tokens per user — delete oldest if over
    const existing = await tx.cliToken.findMany({
      where: { userId: session.user.id },
      orderBy: { createdAt: "asc" },
    });
    if (existing.length >= 5) {
      const toDelete = existing.slice(0, existing.length - 4);
      await tx.cliToken.deleteMany({
        where: { id: { in: toDelete.map((t) => t.id) } },
      });
    }

    await tx.cliToken.create({
      data: {
        token: hashedToken,
        userId: session.user.id,
        expiresAt,
      },
    });
  });

  return NextResponse.json({ token: rawToken, expiresAt: expiresAt.toISOString() });
}

export async function GET() {
  const session = await auth();

  if (!session?.user?.id) {
    return NextResponse.json(
      { error: "UNAUTHORIZED", authenticated: false },
      { status: 401 }
    );
  }

  return NextResponse.json({
    authenticated: true,
    user: {
      name: session.user.name ?? null,
      email: session.user.email ?? null,
    },
  });
}
