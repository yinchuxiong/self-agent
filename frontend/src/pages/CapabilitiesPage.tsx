import { Tabs, Table, Typography } from "antd";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import PageHeader from "../components/PageHeader";
import { EnabledTag, PermissionTag } from "../components/StatusTag";
import type { SkillDefinition, ToolDefinition } from "../types";

export default function CapabilitiesPage() {
  const [skills, setSkills] = useState<SkillDefinition[]>([]);
  const [tools, setTools] = useState<ToolDefinition[]>([]);
  const [mcps, setMcps] = useState<Record<string, unknown>[]>([]);
  const [workflows, setWorkflows] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    void Promise.all([api.skills(), api.tools(), api.mcps(), api.workflows()]).then(
      ([skillRows, toolRows, mcpRows, workflowRows]) => {
        setSkills(skillRows);
        setTools(toolRows);
        setMcps(mcpRows);
        setWorkflows(workflowRows);
      }
    );
  }, []);

  return (
    <div className="pageGrid">
      <PageHeader title="能力管理" subtitle="Skill / Tool / MCP / Workflow 的统一注册视图" />
      <Tabs
        items={[
          {
            key: "skills",
            label: "Skill",
            children: (
              <Table
                rowKey="id"
                dataSource={skills}
                pagination={{ pageSize: 8 }}
                columns={[
                  {
                    title: "Skill",
                    render: (_, record) => (
                      <>
                        <Typography.Text strong>{record.display_name}</Typography.Text>
                        <Typography.Paragraph type="secondary">{record.description}</Typography.Paragraph>
                      </>
                    )
                  },
                  { title: "分类", dataIndex: "category" },
                  { title: "版本", dataIndex: "version" },
                  { title: "状态", render: (_, record) => <EnabledTag enabled={record.enabled} /> },
                  { title: "权限", render: (_, record) => <PermissionTag level={record.permission_level} /> },
                  { title: "确认", render: (_, record) => (record.confirm_required ? "需要" : "不需要") }
                ]}
              />
            )
          },
          {
            key: "tools",
            label: "Tool",
            children: (
              <Table
                rowKey="id"
                dataSource={tools}
                pagination={false}
                columns={[
                  { title: "Tool", dataIndex: "display_name" },
                  { title: "标识", dataIndex: "name" },
                  { title: "所属 Skill", dataIndex: "owner_skill" },
                  { title: "权限", render: (_, record) => <PermissionTag level={record.permission_level} /> },
                  { title: "超时", render: (_, record) => `${record.timeout_seconds}s` }
                ]}
              />
            )
          },
          {
            key: "mcps",
            label: "MCP",
            children: (
              <Table
                rowKey="name"
                dataSource={mcps}
                pagination={false}
                columns={[
                  { title: "MCP", dataIndex: "display_name" },
                  { title: "状态", dataIndex: "status" },
                  { title: "工具数", dataIndex: "tool_count" },
                  { title: "确认", render: (_, record) => (record.confirm_required ? "需要" : "不需要") }
                ]}
              />
            )
          },
          {
            key: "workflows",
            label: "Workflow",
            children: (
              <Table
                rowKey="name"
                dataSource={workflows}
                pagination={false}
                columns={[
                  { title: "Workflow", dataIndex: "display_name" },
                  { title: "触发", dataIndex: "trigger" },
                  { title: "步骤", render: (_, record) => (record.steps as string[]).join(" → ") }
                ]}
              />
            )
          }
        ]}
      />
    </div>
  );
}

