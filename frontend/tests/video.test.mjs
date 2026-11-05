import assert from "node:assert/strict";
import { videoSource } from "../src/lib/video.ts";

assert.deepEqual(videoSource("https://www.youtube.com/watch?v=abc123"), { kind: "embed", src: "https://www.youtube-nocookie.com/embed/abc123" });
assert.deepEqual(videoSource("https://youtu.be/abc123?t=4"), { kind: "embed", src: "https://www.youtube-nocookie.com/embed/abc123" });
assert.deepEqual(videoSource("https://youtube.com/shorts/xyz"), { kind: "embed", src: "https://www.youtube-nocookie.com/embed/xyz" });
assert.deepEqual(videoSource("https://vimeo.com/123456789"), { kind: "embed", src: "https://player.vimeo.com/video/123456789" });
assert.deepEqual(videoSource("https://assets.cdn.example/tour.mp4"), { kind: "file", src: "https://assets.cdn.example/tour.mp4" });
assert.equal(videoSource("http://insecure.example/a.mp4"), null);
assert.equal(videoSource("not a url"), null);
assert.equal(videoSource(null), null);
console.log("video.test passed");
