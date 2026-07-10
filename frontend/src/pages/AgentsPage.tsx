import { ReloadOutlined } from "@ant-design/icons";
import { Button, Space, Switch, Table, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import PageHeader from "../components/PageHeader";
import { EnabledTag, PermissionTag } from "../components/StatusTag";
import type { AgentDefinition } from "../types";

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setAgents(await api.agents());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function toggle(agent: AgentDefinition, enabled: boolean) {
    // Agent enablement is live in the in-memory registry for M1.
    const updated = await api.updateAgent(agent.name, enabled);
    setAgents((current) => current.map((item) => (item.name === updated.name ? updated : item)));
    message.success(`${updated.display_name} 已${enabled ? "启用" : "禁用"}`);
  }

  return (
    <div className="pageGrid">
      <PageHeader
        title="Agent 管理"
        subtitle="查看领域 Agent、权限上限、默认工作目录和已装配 Skill"
        actions={<Button icon={<ReloadOutlined />} onClick={() => void load()} />}
      />
      <Table
        rowKey="id"
        loading={loading}
        dataSource={agents}
        pagination={false}
        columns={[
          {
            title: "Agent",
            dataIndex: "display_name",
            render: (_, record) => (
              <Space direction="vertical" size={0}>
                <Typography.Text strong>{record.display_name}</Typography.Text>
                <Typography.Text type="secondary">{record.description}</Typography.Text>
              </Space>
            )
          },
          { title: "状态", render: (_, record) => <EnabledTag enabled={record.enabled} /> },
          { title: "权限", render: (_, record) => <PermissionTag level={record.permission_level} /> },
          {
            title: "Skill",
            render: (_, record) => record.equipped_skills.join(" / ") || "无"
          },
          {
            title: "启停",
            align: "right",
            render: (_, record) => (
              <Switch checked={record.enabled} onChange={(checked) => void toggle(record, checked)} />
            )
          }
        ]}
      />
    </div>
  );
}
