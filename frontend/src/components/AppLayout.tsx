/**
 * BIM 标书生成 App — 公共布局（UI 阶段 1.1）
 * 侧栏（Sider）+ 主内容区（Content）；子页面通过 Outlet 渲染在 Content 内。
 */
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate, useLocation, Outlet } from 'react-router-dom'
import { Button, Divider, Input, Layout, Menu, Select, Space, Typography } from 'antd'
import { getIdentityScope, getIdentityScopeKey, setIdentityScope } from '../api/client'
import { listPromptProfiles } from '../api/promptProfiles'
import {
  profileIdToSelectValue,
  selectValueToProfileId,
  useSelectedProfile,
} from '../context/SelectedProfileContext'
import { designTokens } from '../theme/tokens'
import '../App.css'

const { Sider, Content } = Layout
const { Title } = Typography

const SIDER_WIDTH = 220

const mainNavItems = [
  { key: '/one-click', label: '一键生成' },
  { key: '/', label: '高级生成' },
  { key: '/compare', label: '修正对比' },
  { key: '/review', label: '标书校审' },
]
const bottomNavItems = [
  { key: '/knowledge-base', label: '知识库' },
  { key: '/scene-template', label: '场景与模板' },
  { key: '/settings', label: '设置' },
]

const contentStyle: React.CSSProperties = {
  padding: designTokens.marginLG,
}

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const currentIdentity = getIdentityScope()
  const identityScope = getIdentityScopeKey()
  const { selectedProfileId, setSelectedProfileId } = useSelectedProfile()
  const [tenantInput, setTenantInput] = useState(currentIdentity.tenantId)
  const [userInput, setUserInput] = useState(currentIdentity.userId)

  const { data: profiles = [], isFetched: profilesFetched } = useQuery({
    queryKey: ['prompt-profiles', identityScope],
    queryFn: listPromptProfiles,
  })

  useEffect(() => {
    if (!profilesFetched || selectedProfileId == null) return
    if (!profiles.some((p) => p.id === selectedProfileId)) {
      setSelectedProfileId(null)
    }
  }, [profilesFetched, profiles, selectedProfileId, setSelectedProfileId])

  const selectedKey =
    location.pathname === '/'
      ? '/'
      : location.pathname.startsWith('/one-click')
        ? '/one-click'
        : location.pathname.startsWith('/knowledge-base')
          ? '/knowledge-base'
          : location.pathname.startsWith('/scene-template')
          ? '/settings'
          : location.pathname.startsWith('/compare')
            ? '/compare'
            : location.pathname.startsWith('/review')
              ? '/review'
              : location.pathname.startsWith('/tasks')
                ? '/'
                : location.pathname

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        width={SIDER_WIDTH}
        style={{
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
          height: '100vh',
          zIndex: 100,
          background: designTokens.colorBgContainer,
          borderRight: `1px solid ${designTokens.colorBorderSecondary}`,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            minHeight: '100vh',
            height: '100%',
          }}
        >
          <div
            style={{
              padding: designTokens.marginLG,
              borderBottom: `1px solid ${designTokens.colorBorderSecondary}`,
              flexShrink: 0,
            }}
          >
            <Title
              level={5}
              style={{
                margin: 0,
                color: designTokens.colorText,
                fontWeight: designTokens.fontWeightStrong,
                fontSize: designTokens.fontSizeHeading5,
              }}
            >
              工程设计标书生成系统
            </Title>
            <Space.Compact style={{ width: '100%', marginTop: designTokens.marginSM }}>
              <Input
                size="small"
                value={tenantInput}
                onChange={(e) => setTenantInput(e.target.value)}
                placeholder="tenant"
              />
              <Input
                size="small"
                value={userInput}
                onChange={(e) => setUserInput(e.target.value)}
                placeholder="user"
              />
              <Button
                size="small"
                onClick={() => {
                  setIdentityScope({ tenantId: tenantInput, userId: userInput })
                  window.location.reload()
                }}
              >
                切换
              </Button>
            </Space.Compact>
            <Space size={4} style={{ marginTop: 6, width: '100%' }}>
              <Button
                size="small"
                type="link"
                style={{ paddingInline: 0 }}
                onClick={() => {
                  setIdentityScope({ tenantId: currentIdentity.tenantId, userId: 'user-a' })
                  window.location.reload()
                }}
              >
                user-a
              </Button>
              <Button
                size="small"
                type="link"
                style={{ paddingInline: 0 }}
                onClick={() => {
                  setIdentityScope({ tenantId: currentIdentity.tenantId, userId: 'user-b' })
                  window.location.reload()
                }}
              >
                user-b
              </Button>
            </Space>
            <Select
              size="small"
              style={{ width: '100%', marginTop: designTokens.marginSM }}
              value={profileIdToSelectValue(selectedProfileId)}
              onChange={(v) => setSelectedProfileId(selectValueToProfileId(v))}
              options={[
                { value: 'default', label: 'BIM技术标（内置）' },
                ...profiles.map((p) => ({
                  value: String(p.id),
                  label: p.is_builtin ? `${p.name}（内置）` : p.name,
                })),
              ]}
              popupMatchSelectWidth={false}
              dropdownRender={(menu) => (
                <>
                  {menu}
                  <Divider style={{ margin: '8px 0' }} />
                  <Button
                    type="link"
                    block
                    onClick={() => {
                      navigate('/scene-template?create=1')
                    }}
                  >
                    创建新配置
                  </Button>
                </>
              )}
            />
          </div>
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
            <Menu
              mode="inline"
              items={mainNavItems}
              selectedKeys={[selectedKey]}
              style={{
                marginTop: designTokens.marginXS,
                borderRight: 'none',
                background: 'transparent',
              }}
              onClick={({ key }) => navigate(key)}
            />
          </div>
          <div
            style={{
              borderTop: `1px solid ${designTokens.colorBorderSecondary}`,
              flexShrink: 0,
            }}
          >
            <Menu
              mode="inline"
              items={bottomNavItems}
              selectedKeys={[selectedKey]}
              style={{
                borderRight: 'none',
                background: 'transparent',
              }}
              onClick={({ key }) => navigate(key)}
            />
          </div>
        </div>
      </Sider>
      <Layout style={{ marginLeft: SIDER_WIDTH, minHeight: '100vh' }}>
        <Content style={contentStyle}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
