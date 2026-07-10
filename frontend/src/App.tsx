import {
  ApartmentOutlined,
  BarChartOutlined,
  CalendarOutlined,
  DatabaseOutlined,
  MessageOutlined,
  SettingOutlined,
  ThunderboltOutlined
} from "@ant-design/icons";
import { Layout, Menu, Typography } from "antd";
import { useMemo, useState } from "react";
import AgentsPage from "./pages/AgentsPage";
import CapabilitiesPage from "./pages/CapabilitiesPage";
import ChatPage from "./pages/ChatPage";
import KnowledgePage from "./pages/KnowledgePage";
import SettingsPage from "./pages/SettingsPage";
import StatisticsPage from "./pages/StatisticsPage";
import TasksPage from "./pages/TasksPage";

const { Sider, Content } = Layout;

const pages = [
  { key: "chat", icon: <MessageOutlined />, label: "对话" },
  { key: "agents", icon: <ApartmentOutlined />, label: "Agent 管理" },
  { key: "capabilities", icon: <ThunderboltOutlined />, label: "能力管理" },
  { key: "knowledge", icon: <DatabaseOutlined />, label: "知识库" },
  { key: "tasks", icon: <CalendarOutlined />, label: "任务" },
  { key: "statistics", icon: <BarChartOutlined />, label: "统计" },
  { key: "settings", icon: <SettingOutlined />, label: "设置" }
];

export default function App() {
  const [active, setActive] = useState("chat");
  const page = useMemo(() => {
    if (active === "agents") return <AgentsPage />;
    if (active === "capabilities") return <CapabilitiesPage />;
    if (active === "knowledge") return <KnowledgePage />;
    if (active === "tasks") return <TasksPage />;
    if (active === "statistics") return <StatisticsPage />;
    if (active === "settings") return <SettingsPage />;
    return <ChatPage />;
  }, [active]);

  return (
    <Layout className="appShell">
      <Sider width={232} className="sideRail">
        <div className="brandBlock">
          <div className="brandMark">SA</div>
          <div>
            <Typography.Title level={4}>个人工作助手</Typography.Title>
            <Typography.Text>Agent 控制台 v0.1</Typography.Text>
          </div>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[active]}
          items={pages}
          onClick={(item) => setActive(item.key)}
        />
      </Sider>
      <Content className="contentShell">{page}</Content>
    </Layout>
  );
}

