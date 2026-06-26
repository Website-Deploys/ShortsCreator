"use client";

/**
 * Creator Profile - the creator's identity and (thin) preferences.
 *
 * In V1 this is a small, explicit, inspectable statement of who the creator is
 * and what the system will and won't do - the seam the future learned Creator
 * (DNA) model grows into.
 */
import { Nav } from "@/components/Nav";
import { Card } from "@/components/ui/Card";

export default function ProfilePage() {
  return (
    <div>
      <Nav />
      <main className="mx-auto max-w-2xl px-6 py-10">
        <h1 className="mb-2 text-2xl font-semibold">Creator profile</h1>
        <p className="mb-8 text-muted">
          What Olympus knows about your style. You own this - it is always inspectable and editable.
        </p>

        <Card className="space-y-4">
          <div>
            <p className="text-sm text-muted">Audience</p>
            <p>Not set yet</p>
          </div>
          <div>
            <p className="text-sm text-muted">Voice</p>
            <p>Learned from your edits over time (coming in a later milestone)</p>
          </div>
          <div>
            <p className="text-sm text-muted">Hard rules</p>
            <p>None set</p>
          </div>
        </Card>
      </main>
    </div>
  );
}
