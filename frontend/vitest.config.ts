import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  // Next.js compiles JSX with the automatic runtime, so the components under
  // test never import React themselves. Vitest has to transform them the same
  // way or rendering them throws "React is not defined".
  esbuild: { jsx: "automatic" },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
});
