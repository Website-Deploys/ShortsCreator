"use client";

/**
 * Settings - account and default preferences.
 *
 * Minimal in V1: default caption style, default length bounds, and hard rules.
 * These are the explicit, inspectable seed of the future Creator (DNA) model.
 */
import { useState } from "react";

import { Nav } from "@/components/Nav";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

export default function SettingsPage() {
  const [captionStyle, setCaptionStyle] = useState("clean");
  const [maxSeconds, setMaxSeconds] = useState(60);
  const [keepPauses, setKeepPauses] = useState(false);

  return (
    <div>
      <Nav />
      <main className="mx-auto max-w-2xl px-6 py-10">
        <h1 className="mb-8 text-2xl font-semibold">Settings</h1>

        <Card className="space-y-6">
          <div>
            <label htmlFor="caption" className="mb-2 block text-sm font-medium">
              Default caption style
            </label>
            <select
              id="caption"
              value={captionStyle}
              onChange={(event) => setCaptionStyle(event.target.value)}
              className="w-full rounded-lg border border-white/10 bg-elevated px-4 py-3 focus:border-accent focus:outline-none"
            >
              <option value="clean">Clean</option>
              <option value="bold">Bold</option>
              <option value="minimal">Minimal</option>
            </select>
          </div>

          <div>
            <label htmlFor="length" className="mb-2 block text-sm font-medium">
              Maximum Short length: {maxSeconds}s
            </label>
            <input
              id="length"
              type="range"
              min={15}
              max={90}
              value={maxSeconds}
              onChange={(event) => setMaxSeconds(Number(event.target.value))}
              className="w-full accent-accent"
            />
          </div>

          <label className="flex items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={keepPauses}
              onChange={(event) => setKeepPauses(event.target.checked)}
              className="h-4 w-4 accent-accent"
            />
            Keep my intentional pauses (do not trim them)
          </label>

          <Button disabled title="Saving preferences arrives with the preferences API">
            Save preferences
          </Button>
        </Card>
      </main>
    </div>
  );
}
