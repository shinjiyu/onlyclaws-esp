// 标题：悬浮透明页
// 控制台下发。需要「在其他应用上层显示」。默认不拦触摸。
function onStart() {
  web.float(
    "<!doctype html><html><head><meta charset=utf-8>" +
      "<meta name=viewport content='width=device-width,initial-scale=1'>" +
      "<style>" +
      "html,body{margin:0;background:transparent;width:100%;height:100%;overflow:hidden}" +
      ".card{position:fixed;left:20px;bottom:140px;padding:12px 16px;border-radius:16px;" +
      "background:rgba(20,18,16,.56);color:#fff;font:15px/1.4 sans-serif;max-width:60vw}" +
      "video{position:fixed;right:16px;top:88px;width:42vw;max-width:280px;border-radius:14px;" +
      "background:transparent;object-fit:cover}" +
      "</style></head><body>" +
      "<div class=card>悬浮透明 WebView<br>下面的桌面应能透出来</div>" +
      "<video id=v autoplay muted loop playsinline " +
      "src='https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.webm'></video>" +
      "</body></html>",
  );
  oca.log("浮层透明页已打开");
}

function onStop() {
  web.clear();
}
