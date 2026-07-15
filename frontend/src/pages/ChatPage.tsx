import { FolderOpenOutlined, PlusOutlined, SendOutlined } from "@ant-design/icons";
import { Button, Empty, Input, List, Select, Space, Spin, Typography, message } from "antd";
import { useEffect, useMemo, useState } from "react";
import { api, streamMessage } from "../api/client";
import PageHeader from "../components/PageHeader";
import type { AgentDefinition, ChatMessage, ChatSession } from "../types";

interface UiMessage {
  id: string;
  role: "user" | "assistant" | "event";
  content: string;
  agent?: string;
}

export default function ChatPage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSession, setActiveSession] = useState<string>();
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [agentName, setAgentName] = useState("auto");
  const [workspaceDir, setWorkspaceDir] = useState("");
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    void boot();
  }, []);

  async function boot() {
    // Load the minimum data needed for the first usable screen: sessions and Agent choices.
    const [sessionList, agentList] = await Promise.all([api.sessions(), api.agents()]);
    setAgents(agentList.filter((agent) => agent.name !== "supervisor"));
    if (sessionList.length > 0) {
      setSessions(sessionList);
      await openSession(sessionList[0].id);
    } else {
      await createSession();
    }
  }

  async function createSession() {
    const session = await api.createSession(workspaceDir);
    setSessions((current) => [session, ...current]);
    setActiveSession(session.id);
    setMessages([]);
  }

  async function openSession(sessionId: string) {
    const detail = await api.session(sessionId);
    setActiveSession(sessionId);
    setMessages(detail.messages.map(toUiMessage));
    // 同步当前工作目录到输入框
    setWorkspaceDir(detail.session.workspace_dir ?? "");
  }

  async function send() {
    if (!draft.trim() || !activeSession) return;
    const content = draft.trim();
    setDraft("");
    setLoading(true);
    setMessages((current) => [
      ...current,
      { id: `local_user_${Date.now()}`, role: "user", content },
      { id: `local_assistant_${Date.now()}`, role: "assistant", content: "" }
    ]);

    try {
      await streamMessage(activeSession, content, agentName, workspaceDir, (event) => {
        // Answer chunks append into the latest assistant bubble.
        if (event.event === "answer_delta") {
          setMessages((current) => {
            const next = [...current];
            const last = next[next.length - 1];
            next[next.length - 1] = { ...last, content: `${last.content}${event.data.delta ?? ""}` };
            return next;
          });
        }
        if (["supervisor_started", "agent_started", "skill_activated"].includes(event.event)) {
          // Runtime milestones are shown inline so users can see how routing happened.
          setMessages((current) => [
            ...current.slice(0, -1),
            {
              id: `${event.event}_${Date.now()}`,
              role: "event",
              content: event.message,
              agent: event.agent ?? undefined
            },
            current[current.length - 1]
          ]);
        }
      });
      const sessionList = await api.sessions();
      setSessions(sessionList);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "发送失败");
    } finally {
      setLoading(false);
    }
  }

  const agentOptions = useMemo(
    () => [
      { value: "auto", label: "自动路由" },
      ...agents.map((agent) => ({ value: agent.name, label: agent.display_name }))
    ],
    [agents]
  );

  return (
    <div className="pageGrid chatLayout">
      <aside className="sessionPane">
        <PageHeader
          title="对话"
          subtitle="Supervisor 路由到领域 Agent"
          actions={<Button icon={<PlusOutlined />} onClick={createSession} />}
        />
        <List
          dataSource={sessions}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无会话" /> }}
          renderItem={(session) => (
            <List.Item
              className={session.id === activeSession ? "sessionItem active" : "sessionItem"}
              onClick={() => void openSession(session.id)}
            >
              <div>
                <Typography.Text ellipsis>{session.title}</Typography.Text>
                {session.workspace_dir ? (
                  <Typography.Text type="secondary" style={{ display: "block", fontSize: 11 }}>
                    {session.workspace_dir}
                  </Typography.Text>
                ) : null}
              </div>
            </List.Item>
          )}
        />
      </aside>
      <main className="chatPane">
        <div className="chatToolbar">
          <Space>
            <Select value={agentName} options={agentOptions} onChange={setAgentName} />
            <Input
              prefix={<FolderOpenOutlined />}
              placeholder="工作目录，如 E:/my-project"
              value={workspaceDir}
              onChange={(event) => setWorkspaceDir(event.target.value)}
              style={{ width: 240 }}
              allowClear
            />
          </Space>
          <Typography.Text type="secondary">SSE 流式事件已接入</Typography.Text>
        </div>
        <div className="messageStack">
          {messages.length === 0 ? (
            <Empty description="发送一条消息，测试 Supervisor 到 Agent 的闭环" />
          ) : (
            messages.map((item) => (
              <div key={item.id} className={`messageBubble ${item.role}`}>
                {item.agent ? <Typography.Text className="messageMeta">{item.agent}</Typography.Text> : null}
                <Typography.Paragraph>{item.content}</Typography.Paragraph>
              </div>
            ))
          )}
          {loading ? <Spin size="small" /> : null}
        </div>
        <div className="composer">
          <Input.TextArea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onPressEnter={(event) => {
              if (!event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
            placeholder="例如：帮我 review 今日代码后生成日报草稿"
            autoSize={{ minRows: 2, maxRows: 5 }}
          />
          <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={() => void send()}>
            发送
          </Button>
        </div>
      </main>
    </div>
  );
}

function toUiMessage(message: ChatMessage): UiMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    agent: message.agent_name
  };
}
