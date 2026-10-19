/**
 * 在 127.0.0.1 上启动 @sansenjian/qq-music-api。
 * 有的版本在被加载时就会监听 PORT，这里避免再监听第二次。
 */
const net = require("net");

const port = Number(process.env.QQ_MUSIC_PORT || process.env.PORT || 3300);
process.env.PORT = String(port);

function portIsFree(targetPort) {
  return new Promise((resolve) => {
    const probe = net.createServer();
    probe.once("error", () => resolve(false));
    probe.once("listening", () => probe.close(() => resolve(true)));
    probe.listen(targetPort, "127.0.0.1");
  });
}

function koaApp(imported) {
  if (imported && typeof imported.listen === "function") return imported;
  if (imported && imported.default && typeof imported.default.listen === "function") {
    return imported.default;
  }
  return null;
}

async function main() {
  const freeBeforeLoad = await portIsFree(port);
  const imported = require("@sansenjian/qq-music-api");
  if (!freeBeforeLoad) {
    process.stdout.write(`QQ music API already listening on 127.0.0.1:${port}\n`);
    return;
  }
  const listenedDuringLoad = !(await portIsFree(port));
  if (listenedDuringLoad) {
    process.stdout.write(`QQ music API listening on 127.0.0.1:${port}\n`);
    return;
  }
  const app = koaApp(imported);
  if (!app) {
    process.stderr.write("QQ music API did not export a listen function\n");
    process.exit(1);
  }
  const server = app.listen(port, "127.0.0.1", () => {
    process.stdout.write(`QQ music API listening on 127.0.0.1:${port}\n`);
  });
  server.on("error", (error) => {
    process.stderr.write(`${error.message}\n`);
    process.exit(1);
  });
}

main().catch((error) => {
  process.stderr.write(`${error && error.stack ? error.stack : error}\n`);
  process.exit(1);
});
