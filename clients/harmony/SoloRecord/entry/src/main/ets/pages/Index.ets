import webview from '@ohos.web.webview';

const DEFAULT_SERVER_URL = 'http://127.0.0.1:8000';

@Entry
@Component
struct Index {
  controller: webview.WebviewController = new webview.WebviewController();
  @State serverUrl: string = DEFAULT_SERVER_URL;

  aboutToAppear(): void {
    webview.WebviewController.setWebDebuggingAccess(false);
  }

  build() {
    Column() {
      Web({ src: this.serverUrl, controller: this.controller })
        .javaScriptAccess(true)
        .domStorageAccess(true)
        .onlineImageAccess(true)
        .fileAccess(false)
        .width('100%')
        .height('100%')
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#f5f7fb')
  }
}
