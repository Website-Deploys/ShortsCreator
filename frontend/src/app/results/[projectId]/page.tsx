"use client";

/**
 * Results screen - deliver the Shorts and minimal controls.
 *
 * Presents the finished Shorts with the reason each was chosen and simple
 * actions (download, regenerate). The clips API arrives in a later milestone;
 * until then this renders a clear, honest scaffold.
 */
import { useParams } from "next/navigation";

import { Nav } from "@/components/Nav";
import { Card } from "@/components/ui/Card";

export default function ResultsPage() {
  const params = useParams<{ projectId: string }>();

  return (
    <div>
      <Nav />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="mb-2 text-2xl font-semibold">Your Shorts</h1>
        <p className="mb-8 text-muted">Project {params.projectId}</p>

        <Card>
          <p className="text-muted">
            Finished Shorts - each with the thesis behind it, a preview, and download - appear here
            once the rendering and clips APIs are delivered. The screen and data flow are wired and
            ready for that milestone.
          </p>
        </Card>
      </main>
    </div>
  );
}
