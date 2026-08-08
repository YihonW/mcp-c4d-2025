import { classifyC4DVersion } from "../compatibility-policy.js";
import { defineTool, textResult } from "./define-tool.js";

type BridgeCapabilities = {
  c4d_version: number;
  [key: string]: unknown;
};

export const getCapabilitiesTool = defineTool({
  name: "get_capabilities",
  group: "basics",
  title: "Get C4D Capabilities",
  description: "Report the Cinema 4D runtime, security posture, and available capabilities.",
  inputShape: {},
  async handler(_args, client) {
    const capabilities = await client.request<BridgeCapabilities>("get_capabilities", {}, 5_000);
    const classified = classifyC4DVersion(capabilities.c4d_version);
    return textResult({
      ...capabilities,
      display_version: classified.display,
      compatibility: classified.status,
    });
  },
});
