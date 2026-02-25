#!/usr/bin/env node
/**
 * MCP fetch server for job-matcher plugin.
 *
 * Zero external dependencies — uses only Node.js stdlib.
 * Implements MCP stdio transport (Content-Length framing) directly.
 *
 * Provides:
 *   fetch_url  — HTTP GET/POST with optional output_file for large responses
 *   verify_url — Check if a job listing URL is still live
 */

import * as https from "node:https";
import * as http from "node:http";
import * as fs from "node:fs";
import * as path from "node:path";

// ─── MCP Protocol Layer (Content-Length framing over stdio) ───────────────────

let inputBuffer = Buffer.alloc(0);

function sendMessage(msg) {
  const json = JSON.stringify(msg);
  const header = `Content-Length: ${Buffer.byteLength(json)}\r\n\r\n`;
  process.stdout.write(header + json);
}

function sendResult(id, result) {
  sendMessage({ jsonrpc: "2.0", id, result });
}

function sendError(id, code, message) {
  sendMessage({ jsonrpc: "2.0", id, error: { code, message } });
}

function processBuffer() {
  while (true) {
    const headerEnd = inputBuffer.indexOf("\r\n\r\n");
    if (headerEnd === -1) break;

    const header = inputBuffer.subarray(0, headerEnd).toString();
    const match = header.match(/Content-Length:\s*(\d+)/i);
    if (!match) {
      inputBuffer = inputBuffer.subarray(headerEnd + 4);
      continue;
    }

    const contentLength = parseInt(match[1], 10);
    const messageStart = headerEnd + 4;

    if (inputBuffer.length < messageStart + contentLength) break;

    const body = inputBuffer
      .subarray(messageStart, messageStart + contentLength)
      .toString();
    inputBuffer = inputBuffer.subarray(messageStart + contentLength);

    try {
      handleMessage(JSON.parse(body));
    } catch {
      // ignore parse errors
    }
  }
}

process.stdin.on("data", (chunk) => {
  inputBuffer = Buffer.concat([inputBuffer, chunk]);
  processBuffer();
});

// ─── MCP Request Router ──────────────────────────────────────────────────────

function handleMessage(msg) {
  switch (msg.method) {
    case "initialize":
      sendResult(msg.id, {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "job-matcher-fetch", version: "1.0.0" },
      });
      break;

    case "notifications/initialized":
      break; // notification — no response

    case "tools/list":
      sendResult(msg.id, { tools: TOOLS });
      break;

    case "tools/call":
      handleToolCall(
        msg.id,
        msg.params.name,
        msg.params.arguments || {}
      );
      break;

    case "ping":
      sendResult(msg.id, {});
      break;

    default:
      if (msg.id !== undefined) {
        sendError(msg.id, -32601, `Unknown method: ${msg.method}`);
      }
  }
}

// ─── Tool Definitions ────────────────────────────────────────────────────────

const TOOLS = [
  {
    name: "fetch_url",
    description:
      "Fetch a URL via HTTP GET or POST. When output_file is set, writes the " +
      "response body directly to disk and returns only small status metadata " +
      "(use this for large API responses to avoid output size limits).",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", description: "URL to fetch" },
        method: {
          type: "string",
          description: "HTTP method",
          default: "GET",
        },
        headers: {
          type: "object",
          description: "Custom HTTP headers (key-value pairs)",
          additionalProperties: { type: "string" },
        },
        body: {
          type: "string",
          description: "Request body for POST requests",
        },
        timeout: {
          type: "number",
          description: "Timeout in milliseconds (default: 30000)",
          default: 30000,
        },
        output_file: {
          type: "string",
          description:
            "File path to write the response body to. When set, the tool " +
            "returns only { status_code, content_length, output_file } " +
            "instead of the full body.",
        },
      },
      required: ["url"],
    },
  },
  {
    name: "verify_url",
    description:
      "Check if a job listing URL is still live. Performs HTTP GET, scans " +
      "the page for expired/closed indicators, and checks for redirects " +
      "to generic careers pages.",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", description: "Job listing URL to verify" },
      },
      required: ["url"],
    },
  },
];

// ─── HTTP Fetch (stdlib, supports redirects) ─────────────────────────────────

function httpRequest(url, options = {}) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const mod = parsed.protocol === "https:" ? https : http;
    const method = (options.method || "GET").toUpperCase();
    const redirectCount = options._redirectCount || 0;

    const headers = {
      "User-Agent": "JobMatcher/2.0 (job search tool)",
      ...(options.headers || {}),
    };

    if (method === "POST" && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }

    const req = mod.request(
      parsed,
      { method, headers, timeout: options.timeout || 30000 },
      (res) => {
        // Follow redirects (up to 5)
        if (
          [301, 302, 303, 307, 308].includes(res.statusCode) &&
          res.headers.location &&
          redirectCount < 5
        ) {
          const next = new URL(res.headers.location, url).toString();
          res.resume(); // drain the response
          resolve(
            httpRequest(next, {
              ...options,
              // 303 always becomes GET
              method: res.statusCode === 303 ? "GET" : method,
              _redirectCount: redirectCount + 1,
              _originalUrl: options._originalUrl || url,
            })
          );
          return;
        }

        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () =>
          resolve({
            statusCode: res.statusCode,
            headers: res.headers,
            body: Buffer.concat(chunks).toString("utf-8"),
            finalUrl: url,
            originalUrl: options._originalUrl || url,
          })
        );
      }
    );

    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error(`Request timed out after ${options.timeout || 30000}ms`));
    });

    if (options.body) req.write(options.body);
    req.end();
  });
}

// ─── Tool: fetch_url ─────────────────────────────────────────────────────────

async function fetchUrl(args) {
  const {
    url,
    method = "GET",
    headers = {},
    body,
    timeout = 30000,
    output_file,
  } = args;

  const result = await httpRequest(url, { method, headers, body, timeout });

  if (output_file) {
    const dir = path.dirname(output_file);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(output_file, result.body, "utf-8");
    return JSON.stringify({
      status_code: result.statusCode,
      content_length: Buffer.byteLength(result.body),
      output_file,
      final_url: result.finalUrl,
    });
  }

  // Small responses: return inline
  return result.body;
}

// ─── Tool: verify_url ────────────────────────────────────────────────────────

const EXPIRED_PHRASES = [
  "no longer available",
  "no longer accepting",
  "position has been filled",
  "position filled",
  "this job has been closed",
  "this job is closed",
  "this role has been filled",
  "this posting has expired",
  "this listing has expired",
  "applications are closed",
  "applications are no longer being accepted",
  "this job has expired",
  "this opportunity is closed",
  "this position is no longer available",
  "job not found",
  "the position you are looking for is no longer",
  "this role is no longer open",
];

async function verifyUrl(args) {
  const { url } = args;

  try {
    const result = await httpRequest(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
          "AppleWebKit/537.36 (KHTML, like Gecko) " +
          "Chrome/120.0.0.0 Safari/537.36",
      },
      timeout: 15000,
    });

    // HTTP 404/410 → expired
    if (result.statusCode === 404 || result.statusCode === 410) {
      return JSON.stringify({
        url,
        status: "EXPIRED",
        http_code: result.statusCode,
        reason: `HTTP ${result.statusCode} response`,
      });
    }

    // HTTP 403 or connection failure
    if (result.statusCode === 403) {
      return JSON.stringify({
        url,
        status: "UNVERIFIABLE",
        http_code: result.statusCode,
        reason: "Access denied",
      });
    }

    // Other errors
    if (result.statusCode >= 400) {
      return JSON.stringify({
        url,
        status: "UNVERIFIABLE",
        http_code: result.statusCode,
        reason: `HTTP ${result.statusCode}`,
      });
    }

    // Scan body for expired phrases
    const bodyLower = result.body.toLowerCase();
    for (const phrase of EXPIRED_PHRASES) {
      if (bodyLower.includes(phrase)) {
        return JSON.stringify({
          url,
          status: "EXPIRED",
          http_code: result.statusCode,
          reason: `Page contains: "${phrase}"`,
        });
      }
    }

    // Check for redirect to generic careers page
    if (result.finalUrl !== result.originalUrl) {
      const finalPath = new URL(result.finalUrl).pathname.toLowerCase();
      if (/^\/(careers|jobs|openings|positions)\/?$/.test(finalPath)) {
        return JSON.stringify({
          url,
          status: "EXPIRED",
          http_code: result.statusCode,
          reason: `Redirected to generic page: ${result.finalUrl}`,
        });
      }
    }

    return JSON.stringify({
      url,
      status: "VERIFIED",
      http_code: result.statusCode,
      reason: "Page loads with no expired indicators",
    });
  } catch (e) {
    return JSON.stringify({
      url,
      status: "UNVERIFIABLE",
      http_code: 0,
      reason: e.message,
    });
  }
}

// ─── Tool Call Dispatcher ────────────────────────────────────────────────────

async function handleToolCall(id, name, args) {
  try {
    let result;
    if (name === "fetch_url") {
      result = await fetchUrl(args);
    } else if (name === "verify_url") {
      result = await verifyUrl(args);
    } else {
      return sendError(id, -32602, `Unknown tool: ${name}`);
    }
    sendResult(id, {
      content: [{ type: "text", text: result }],
    });
  } catch (e) {
    sendResult(id, {
      content: [{ type: "text", text: JSON.stringify({ error: e.message }) }],
      isError: true,
    });
  }
}

// ─── Start ───────────────────────────────────────────────────────────────────

process.stdin.resume();
process.stderr.write("job-matcher-fetch MCP server started\n");
