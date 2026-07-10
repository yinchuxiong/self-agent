import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#2f6fed",
          colorSuccess: "#5f7c61",
          colorWarning: "#b4894d",
          colorError: "#a6535f",
          colorTextBase: "#1e2530",
          colorBgBase: "#f5f6f2",
          borderRadius: 8,
          fontFamily:
            "'Aptos', 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', sans-serif"
        },
        components: {
          Layout: { bodyBg: "#f5f6f2", siderBg: "#1e2530", headerBg: "#f5f6f2" },
          Card: { borderRadiusLG: 8 },
          Button: { borderRadius: 7 }
        }
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>
);

