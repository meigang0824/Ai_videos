import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Play,
  Link2,
  CheckCircle2,
  RefreshCcw,
  Copy,
  Wand2,
  Mic2,
  Clock3,
  FileText,
  Download,
  Volume2,
  Loader2,
  AlertCircle,
  Scissors,
  UserRound,
  AudioLines,
  SlidersHorizontal,
  Film,
  Upload,
  ArrowDown,
  ArrowUp,
  Trash2,
  Database,
  History
} from 'lucide-react';
import './app.css';

const API_BASE = '';
const AUTH_TOKEN_KEY = 'cosyvoice_auth_token';
const TRANSIENT_HTTP_STATUS = new Set([502, 503, 504]);
const DEFAULT_JOB_TIMEOUT_MS = 8 * 60 * 1000;

const defaultPrompt = {
  url: ''
};

const FALLBACK_BACKGROUND_VIDEO = '';

const VIDEO_RATIOS = [
  { id: 'vertical', name: '9:16', width: 720, height: 1280 },
  { id: 'wide', name: '16:9', width: 1280, height: 720 },
  { id: 'keep', name: '原始', width: 0, height: 0 }
];

const VIDEO_RENDER_PRESETS = [
  { id: 'balanced', name: '标准', crf: 18, fps: 30, ffmpegPreset: 'medium', subtitleTiming: 'estimated' },
  { id: 'fast', name: '极速', crf: 24, fps: 25, ffmpegPreset: 'veryfast', subtitleTiming: 'estimated' },
  { id: 'quality', name: '高清', crf: 16, fps: 30, ffmpegPreset: 'slow', subtitleTiming: 'estimated' }
];

const SUBTITLE_STYLES = [
  { id: 'classic', name: '经典白字' },
  { id: 'yellow', name: '醒目黄字' },
  { id: 'clean', name: '干净描边' },
  { id: 'bold', name: '粗体黑底' }
];

const SUBTITLE_SIZES = [
  { id: 'small', name: '小' },
  { id: 'normal', name: '中' },
  { id: 'large', name: '大' }
];

const SUBTITLE_COLORS = [
  { id: '#ffffff', name: '白色' },
  { id: '#ffe650', name: '黄色' },
  { id: '#45f3a3', name: '绿色' },
  { id: '#ff5d7a', name: '红色' }
];

const TTS_SPEED_OPTIONS = [
  { id: 0.8, name: '慢速 0.8x' },
  { id: 0.9, name: '稍慢 0.9x' },
  { id: 1.0, name: '正常 1.0x' },
  { id: 1.1, name: '稍快 1.1x' },
  { id: 1.2, name: '快速 1.2x' },
  { id: 1.3, name: '更快 1.3x' }
];

const PREVIEWABLE_MEDIA_RE = /^(https?:|\/api\/|\/assets\/)/i;
const HISTORY_LIMIT = 200;
const HIDDEN_HISTORY_PREFIXES = [['di', 'gi', 'tal_'].join(''), ['kl', 'ing_'].join('')];
const HISTORY_CATEGORIES = [
  { id: 'all', label: '全部' },
  { id: 'video', label: '成片' },
  { id: 'wav2lip', label: '口型' },
  { id: 'tts', label: '配音' },
  { id: 'script', label: '文案' },
  { id: 'active', label: '处理中' },
  { id: 'failed', label: '失败' }
];

const DEFAULT_REWRITE_OPTIONS = {
  styles: [
    { id: 'viral', name: '爆款钩子', desc: '强开头、强节奏' },
    { id: 'story', name: '故事叙事', desc: '人物、冲突、反转' },
    { id: 'knowledge', name: '干货科普', desc: '清晰可信、信息密度高' },
    { id: 'emotional', name: '情绪共鸣', desc: '代入感和情绪价值' },
    { id: 'sales', name: '种草转化', desc: '痛点、利益点、行动引导' },
    { id: 'plain', name: '自然口播', desc: '少套路，更像真人表达' }
  ],
  tones: [
    { id: 'natural', name: '自然' },
    { id: 'sharp', name: '犀利' },
    { id: 'warm', name: '温暖' },
    { id: 'professional', name: '专业' },
    { id: 'suspense', name: '悬念' }
  ],
  lengths: [
    { id: 'short', name: '短', desc: '150-250 字' },
    { id: 'medium', name: '中', desc: '250-400 字' },
    { id: 'long', name: '长', desc: '400-600 字' }
  ],
  platforms: [
    { id: 'douyin', name: '抖音/快手' },
    { id: 'xiaohongshu', name: '小红书' },
    { id: 'bilibili', name: 'B站' },
    { id: 'wechat', name: '视频号' }
  ],
  strengths: [
    { id: 'light', name: '轻度' },
    { id: 'balanced', name: '平衡' },
    { id: 'heavy', name: '深度' }
  ]
};

const REWRITE_ENGINES = [
  { id: 'ai', name: 'AI 深度', desc: '质量优先，耗时更久' },
  { id: 'fast', name: '快速预览', desc: '秒级返回，质量一般' }
];

const ROLE_LABELS = {
  admin: '管理员',
  user: '普通用户',
  realtor: '房产中介'
};

const REALTOR_OPTIONS = {
  propertyType: ['住宅', '公寓', '别墅', '商铺', '写字楼'],
  dealType: ['二手房', '新房', '租房'],
  layout: ['一居', '两居', '三居', '四居', '五居及以上', '大平层'],
  size: ['60平以下', '60-90平', '90-120平', '120-150平', '150平以上'],
  decoration: ['毛坯', '简装', '精装', '豪装', '拎包入住'],
  orientation: ['南向', '南北通透', '东边套', '西边套', '全明格局'],
  floor: ['低楼层', '中楼层', '高楼层', '顶楼', '带院子', '带露台'],
  elevator: ['电梯房', '洋房低密', '一梯一户', '两梯四户'],
  metro: ['近地铁', '近公交', '自驾方便', '商圈步行可达'],
  school: ['优质学区', '近学校', '近幼儿园', '无学区需求'],
  highlights: ['满五唯一', '税费低', '业主急售', '价格可谈', '采光好', '视野开阔', '安静不临街', '得房率高', '户型方正', '近地铁', '近商圈', '带车位', '带花园', '带露台', '拎包入住'],
  audience: ['刚需首套', '改善家庭', '二胎家庭', '老人同住', '年轻白领', '投资出租', '学区家庭', '养老自住'],
  contentDuration: ['15秒（约80-120字）', '30秒（约160-220字）', '45秒（约240-320字）', '60秒（约320-420字）', '90秒（约450-600字）'],
  style: ['成交转化', '稀缺急迫', '生活场景', '专业讲盘', '探房口播', '高端质感'],
  callToAction: ['预约看房', '私信拿底价', '评论区问房源', '领取房源清单', '了解税费方案']
};

const REALTOR_DURATION_META = {
  '15秒（约80-120字）': { words: '80-120 字', rewriteLength: 'short' },
  '30秒（约160-220字）': { words: '160-220 字', rewriteLength: 'medium' },
  '45秒（约240-320字）': { words: '240-320 字', rewriteLength: 'medium' },
  '60秒（约320-420字）': { words: '320-420 字', rewriteLength: 'long' },
  '90秒（约450-600字）': { words: '450-600 字', rewriteLength: 'long' }
};

const DEFAULT_SERVICE_CONFIG = {
  llm: {
    enabled: false,
    url: '',
    apiKey: '',
    model: '',
    timeout: 90
  },
  asr: {
    enabled: false,
    url: '',
    videoUrl: '',
    apiKey: '',
    model: 'base',
    timeout: 180
  },
  tts: {
    enabled: false,
    url: '',
    cloneUrl: '',
    apiKey: '',
    timeout: 240
  },
  lipSync: {
    enabled: false,
    url: '',
    apiKey: '',
    outputMode: 'binary',
    videoPath: 'video_url',
    base64Path: 'video',
    timeout: 900
  },
  videoCompose: {
    enabled: false,
    url: '',
    apiKey: '',
    timeout: 900
  }
};

const API_CONFIG_SECTIONS = [
  { id: 'llm', title: '文案改写 LLM', hint: 'OpenAI-compatible 文案改写接口' },
  { id: 'asr', title: '文案提取 ASR', hint: '支持链接、音频文件、视频文件转写' },
  { id: 'tts', title: '语音合成 TTS', hint: '普通合成和 clone 音色合成' },
  { id: 'lipSync', title: '口型同步', hint: '上传视频和音频后返回成片' },
  { id: 'videoCompose', title: '视频剪辑成片', hint: '使用 OSS 链接调用外部视频合成接口' }
];

function getAuthToken() {
  try {
    return localStorage.getItem(AUTH_TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

function setAuthToken(token) {
  try {
    if (token) {
      localStorage.setItem(AUTH_TOKEN_KEY, token);
    } else {
      localStorage.removeItem(AUTH_TOKEN_KEY);
    }
  } catch {
    // 浏览器禁用存储时，当前会话仍可继续未登录模式。
  }
}

function authHeaders(extra = {}) {
  const token = getAuthToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

function withAuthQuery(value) {
  const token = getAuthToken();
  if (!token || !value || !value.startsWith('/api/')) return value;
  if (value.includes('access_token=')) return value;
  return `${value}${value.includes('?') ? '&' : '?'}access_token=${encodeURIComponent(token)}`;
}

function withCacheBust(value) {
  if (!value) return value;
  return `${value}${value.includes('?') ? '&' : '?'}t=${Date.now()}`;
}

function previewVideoUrl(result = {}) {
  return result.external_video_url || result.video_object_url || result.object_url || result.outputVideoUrl || result.output_video_url || result.video_url || '';
}

function previewAudioUrl(result = {}) {
  return result.audio_object_url || result.object_url || result.audio_url || '';
}

function previewSubtitleUrl(result = {}) {
  return result.subtitle_object_url || result.subtitle_url || '';
}

function historyItemCategory(item = {}) {
  if (item.status === 'queued' || item.status === 'running') return 'active';
  if (item.status === 'failed' || item.status === 'canceled') return 'failed';
  if (item.kind === 'video') return 'video';
  if (item.kind === 'wav2lip') return 'wav2lip';
  if (item.kind === 'tts') return 'tts';
  if (item.kind === 'extract' || item.kind === 'rewrite') return 'script';
  return 'other';
}

function Stat({ label, value, icon, tone }) {
  return <div className="stat-card">
    <div><span>{label}</span><strong>{value}</strong></div>
    <div className={`stat-icon ${tone}`}>{icon}</div>
  </div>;
}

function Section({ num, title, sub, children, className = '', id }) {
  return <section id={id} className={`panel section ${className}`}>
    <div className="section-title">
      <b>{num}</b>
      <div><h3>{title}</h3>{sub && <span>{sub}</span>}</div>
    </div>
    {children}
  </section>;
}

function StatusLine({ state, text }) {
  if (!text) return null;
  const icon = state === 'loading'
    ? <Loader2 size={16}/>
    : state === 'error'
      ? <AlertCircle size={16}/>
      : <CheckCircle2 size={16}/>;
  return <div className={`status-line ${state}`}>{icon}<span>{text}</span></div>;
}

function OperationHint({ show, children }) {
  if (!show) return null;
  return <div className="operation-hint"><Clock3 size={15}/><span>{children}</span></div>;
}

function asSeconds(ms) {
  if (!ms) return '-';
  return `${(ms / 1000).toFixed(1)}s`;
}

function rewriteFallbackMessage(reason) {
  if (!reason) return 'AI 未返回，已用快速改写兜底，';
  if (reason.includes('missing LLM_API_KEY') || reason.includes('DASHSCOPE_API_KEY')) {
    return '缺少 AI API Key，已用快速改写兜底，';
  }
  if (reason.toLowerCase().includes('timed out')) {
    return 'AI 超时，已用快速改写兜底，';
  }
  return `AI 改写失败（${reason}），已用快速改写兜底，`;
}

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / Math.pow(1024, index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

async function postJSON(path, payload) {
  const started = performance.now();
  const target = /^https?:\/\//i.test(path) ? path : `${API_BASE}${path}`;
  const res = await fetch(target, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload)
  });
  const elapsedMs = performance.now() - started;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.detail || `请求失败：${res.status}`);
    error.status = res.status;
    throw error;
  }
  return { data, elapsedMs };
}

async function getJSON(path) {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.detail || `请求失败：${res.status}`);
    error.status = res.status;
    throw error;
  }
  return data;
}

async function putJSON(path, payload) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'PUT',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload)
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.detail || `请求失败：${res.status}`);
    error.status = res.status;
    throw error;
  }
  return data;
}

async function patchJSON(path, payload) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'PATCH',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload)
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.detail || `请求失败：${res.status}`);
    error.status = res.status;
    throw error;
  }
  return data;
}

async function deleteJSON(path) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'DELETE',
    headers: authHeaders()
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.detail || `请求失败：${res.status}`);
    error.status = res.status;
    throw error;
  }
  return data;
}

async function audioExists(path) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: authHeaders({ Range: 'bytes=0-0' }),
    cache: 'no-store'
  }).catch(() => null);
  return Boolean(res && (res.ok || res.status === 206));
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function wrapPreviewCaption(text, maxChars) {
  const clean = (text || '字幕预览会根据字数自动换行方便你调整样式').replace(/\s+/g, '');
  const size = Math.max(6, Math.min(24, Number(maxChars) || 12));
  const lines = [];
  for (let index = 0; index < clean.length && lines.length < 3; index += size) {
    lines.push(clean.slice(index, index + size));
  }
  return lines.join('\n');
}

function normalizeScriptText(text) {
  return (text || '')
    .split(/\n+/)
    .map(line => {
      const clean = line.replace(/\s+/g, '').replace(/^[，、：:,.]+|[，、：:,.]+$/g, '').trim();
      if (!clean) return '';
      return /[。！？!?；;，,]$/.test(clean) ? clean : `${clean}。`;
    })
    .filter(Boolean)
    .join('');
}

function buildRealtorSource(form) {
  const fields = [
    ['城市片区', form.area],
    ['小区楼盘', form.community],
    ['房源类型', form.propertyType],
    ['交易类型', form.dealType],
    ['户型', form.layout],
    ['面积段', form.size],
    ['价格段', form.price],
    ['装修', form.decoration],
    ['朝向采光', form.orientation],
    ['楼层特点', form.floor],
    ['电梯梯户', form.elevator],
    ['交通配套', form.metro],
    ['教育配套', form.school],
    ['核心卖点', (form.highlights || []).join('、')],
    ['目标客户', (form.audience || []).join('、')],
    ['内容时长', form.contentDuration],
    ['文案风格', form.style],
    ['行动引导', form.callToAction],
    ['补充信息', form.notes]
  ];
  return fields
    .map(([label, value]) => `${label}：${String(value || '').trim()}`)
    .filter(line => !line.endsWith('：'))
    .join('\n');
}

function buildRealtorContext(form) {
  return {
    area: form.area,
    community: form.community,
    propertyType: form.propertyType,
    dealType: form.dealType,
    layout: form.layout,
    size: form.size,
    price: form.price,
    decoration: form.decoration,
    orientation: form.orientation,
    floor: form.floor,
    elevator: form.elevator,
    metro: form.metro,
    school: form.school,
    highlights: Array.isArray(form.highlights) ? form.highlights : [],
    audience: Array.isArray(form.audience) ? form.audience : [],
    contentDuration: form.contentDuration,
    style: form.style,
    callToAction: form.callToAction,
    notes: form.notes
  };
}

function SelectField({ label, options, value, onChange }) {
  return <label>
    <span>{label}</span>
    <select
      value={value || ''}
      onChange={event => onChange(event.target.value)}
    >
      <option value="">请选择</option>
      {options.map(option => <option key={option} value={option}>{option}</option>)}
    </select>
  </label>;
}

function MultiSelectField({ label, options, value, onChange }) {
  const selected = Array.isArray(value) ? value : [];
  const summary = selected.length
    ? `${selected.slice(0, 3).join('、')}${selected.length > 3 ? ` 等${selected.length}项` : ''}`
    : '请选择';

  function toggleOption(option) {
    const next = selected.includes(option)
      ? selected.filter(item => item !== option)
      : [...selected, option];
    onChange(next);
  }

  return <div className="multi-select-field">
    <span>{label}</span>
    <details className="multi-select-dropdown">
      <summary>
        <span>{summary}</span>
        <ArrowDown size={14}/>
      </summary>
      <div className="multi-select-menu">
        {options.map(option => (
          <label key={option} className="multi-select-option">
            <input
              type="checkbox"
              checked={selected.includes(option)}
              onChange={() => toggleOption(option)}
            />
            <span>{option}</span>
          </label>
        ))}
      </div>
    </details>
  </div>;
}

function ApiConfigPanel({ config, status, onClose, onChange, onSave, embedded = false }) {
  const current = config || DEFAULT_SERVICE_CONFIG;

  function field(section, key, label, type = 'text', placeholder = '') {
    const value = current[section]?.[key];
    return <label>
      <span>{label}</span>
      <input
        type={type}
        value={value ?? ''}
        placeholder={placeholder}
        onChange={e => onChange(section, key, type === 'number' ? Number(e.target.value) : e.target.value)}
      />
    </label>;
  }

  const content = <div className={embedded ? 'api-config-panel embedded' : 'api-config-panel'}>
      <div className="api-config-head">
        <div>
          <h2>接口配置</h2>
          <p>后端只负责编排任务，模型能力全部从这里配置的接口调用</p>
        </div>
        {onClose && <button className="ghost small" onClick={onClose}>关闭</button>}
      </div>
      <div className="api-config-grid">
        {API_CONFIG_SECTIONS.map(section => (
          <section className="api-config-card" key={section.id}>
            <div className="api-config-card-head">
              <label className="toggle-line">
                <input
                  type="checkbox"
                  checked={Boolean(current[section.id]?.enabled)}
                  onChange={e => onChange(section.id, 'enabled', e.target.checked)}
                />
                {section.title}
              </label>
              <span>{section.hint}</span>
            </div>
            <div className="api-config-fields">
              {section.id === 'asr' ? (
                <>
                  {field('asr', 'url', '视频链接提取接口', 'text', 'https://.../v1/audio/transcribe-url')}
                  {field('asr', 'videoUrl', '视频文件提取接口', 'text', 'https://.../v1/video/transcribe')}
                </>
              ) : field(section.id, 'url', '接口地址', 'text', 'https://...')}
              {field(section.id, 'apiKey', 'API Key', 'password', '留空表示不修改已保存 Key')}
              {(section.id === 'llm' || section.id === 'asr') && field(section.id, 'model', '模型名')}
              {field(section.id, 'timeout', '超时秒数', 'number')}
              {section.id === 'tts' && (
                <>
                  {field('tts', 'cloneUrl', '声音克隆接口')}
                </>
              )}
            </div>
          </section>
        ))}
      </div>
      <div className="api-config-actions">
        <StatusLine state={status.state} text={status.message}/>
        <button className="primary" onClick={onSave} disabled={status.state === 'loading'}>
          {status.state === 'loading' ? <Loader2 size={18}/> : <CheckCircle2 size={18}/>}保存接口配置
        </button>
      </div>
    </div>;

  if (embedded) return content;
  return <div className="api-config-backdrop">{content}</div>;
}

function AuthPanel({ form, status, onChange, onSubmit, onClose, embedded = false }) {
  const content = <div className={embedded ? 'auth-panel embedded' : 'auth-panel'}>
      <div className="api-config-head">
        <div>
          <h2>登录</h2>
          <p>登录后可使用受保护操作</p>
        </div>
        {onClose && <button className="ghost small" onClick={onClose}>关闭</button>}
      </div>
      <div className="auth-fields">
        <label>
          <span>用户名</span>
          <input
            value={form.username}
            autoComplete="username"
            onChange={e => onChange('username', e.target.value)}
            placeholder="至少 3 个字符"
          />
        </label>
        <label>
          <span>密码</span>
          <input
            type="password"
            value={form.password}
            autoComplete="current-password"
            onChange={e => onChange('password', e.target.value)}
            placeholder="至少 8 个字符"
          />
        </label>
      </div>
      <div className="auth-actions">
        <button className="primary" onClick={onSubmit} disabled={status.state === 'loading'}>
          {status.state === 'loading' ? <Loader2 size={18}/> : <CheckCircle2 size={18}/>}
          登录
        </button>
      </div>
      <StatusLine state={status.state} text={status.message}/>
    </div>;

  if (embedded) return content;
  return <div className="api-config-backdrop">{content}</div>;
}

function formatTime(value) {
  if (!value) return '-';
  const timestamp = String(value).length <= 10 ? Number(value) * 1000 : Number(value);
  if (!Number.isFinite(timestamp)) return '-';
  return new Date(timestamp).toLocaleString();
}

function AdminPage({
  authUser,
  authForm,
  authStatus,
  onAuthChange,
  onLogin,
  onLogout,
  serviceConfig,
  serviceConfigStatus,
  onConfigChange,
  onConfigSave,
  users,
  usersStatus,
  newUser,
  onNewUserChange,
  onCreateUser,
  onDeleteUser,
  onRefreshUsers
}) {
  if (!authUser) {
    return <div className="app-shell admin-shell">
      <section className="workspace admin-workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Admin Console</p>
            <h2>后台管理</h2>
          </div>
          <div className="top-actions">
            <a className="ghost small" href="/">返回工作台</a>
          </div>
        </header>
        <div className="admin-login-panel">
          <AuthPanel
            embedded
            form={authForm}
            status={authStatus}
            onChange={onAuthChange}
            onSubmit={onLogin}
          />
        </div>
      </section>
    </div>;
  }

  if (authUser.role !== 'admin') {
    return <div className="app-shell admin-shell">
      <section className="workspace admin-workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Admin Console</p>
            <h2>后台管理</h2>
          </div>
          <div className="top-actions">
            <span className="auth-badge">{authUser.username}</span>
            <button className="ghost small" onClick={onLogout}>退出</button>
            <a className="ghost small" href="/">返回工作台</a>
          </div>
        </header>
        <section className="admin-card">
          <h3>需要管理员权限</h3>
          <p>当前账号不是管理员，无法访问后台管理功能。</p>
        </section>
      </section>
    </div>;
  }

  return <div className="app-shell admin-shell">
    <section className="workspace admin-workspace">
      <header className="topbar">
        <div>
          <p className="eyebrow">Admin Console</p>
          <h2>后台管理</h2>
        </div>
        <div className="top-actions">
          <span className="auth-badge">{authUser.username} · 管理员</span>
          <button className="ghost small" onClick={onLogout}>退出</button>
          <a className="ghost small" href="/">返回工作台</a>
        </div>
      </header>

      <main className="admin-layout">
        <ApiConfigPanel
          embedded
          config={serviceConfig}
          status={serviceConfigStatus}
          onChange={onConfigChange}
          onSave={onConfigSave}
        />

        <section className="admin-card">
          <div className="admin-card-head">
            <div>
              <h3>用户管理</h3>
              <p>由管理员统一新增或删除用户账号</p>
            </div>
            <button className="ghost small" onClick={onRefreshUsers}><RefreshCcw size={16}/>刷新</button>
          </div>

          <div className="admin-user-form">
            <label>
              <span>用户名</span>
              <input value={newUser.username} onChange={e => onNewUserChange('username', e.target.value)} placeholder="至少 3 个字符"/>
            </label>
            <label>
              <span>密码</span>
              <input type="password" value={newUser.password} onChange={e => onNewUserChange('password', e.target.value)} placeholder="至少 8 个字符"/>
            </label>
            <label>
              <span>角色</span>
              <select value={newUser.role} onChange={e => onNewUserChange('role', e.target.value)}>
                <option value="user">普通用户</option>
                <option value="realtor">房产中介</option>
                <option value="admin">管理员</option>
              </select>
            </label>
            <button className="primary" onClick={onCreateUser} disabled={usersStatus.state === 'loading'}>
              <UserRound size={18}/>新增用户
            </button>
          </div>
          <StatusLine state={usersStatus.state} text={usersStatus.message}/>

          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>用户名</th>
                  <th>角色</th>
                  <th>状态</th>
                  <th>创建时间</th>
                  <th>最后登录</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {users.length ? users.map(user => (
                  <tr key={user.id}>
                    <td data-label="用户名">{user.username}</td>
                    <td data-label="角色">{ROLE_LABELS[user.role] || user.role}</td>
                    <td data-label="状态">{user.status}</td>
                    <td data-label="创建时间">{formatTime(user.created_at)}</td>
                    <td data-label="最后登录">{formatTime(user.last_login_at)}</td>
                    <td data-label="操作">
                      <button
                        className="ghost small danger"
                        onClick={() => onDeleteUser(user)}
                        disabled={user.id === authUser.id}
                      >
                        <Trash2 size={15}/>删除
                      </button>
                    </td>
                  </tr>
                )) : (
                  <tr><td colSpan="6">暂无用户</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </section>
  </div>;
}

async function runBackgroundJob(path, payload, onProgress, options = {}) {
  const started = performance.now();
  const timeoutMs = Number(options.timeoutMs) || DEFAULT_JOB_TIMEOUT_MS;
  const { data: queued } = await postJSON(path, payload);
  let task = null;
  let transientErrors = 0;
  let polls = 0;
  while (true) {
    const elapsed = performance.now() - started;
    if (elapsed > timeoutMs) {
      throw new Error('任务等待超时，请刷新作品记录后重试');
    }
    try {
      task = await getJSON(`/api/v1/jobs/${queued.task_id}`);
      transientErrors = 0;
    } catch (err) {
      if (TRANSIENT_HTTP_STATUS.has(err.status) && transientErrors < 6) {
        transientErrors += 1;
        onProgress?.({ status: 'running', message: '服务正在恢复连接，继续等待', progress: task?.progress || 0 });
        await sleep(1500);
        continue;
      }
      throw err;
    }
    if (task.status === 'success') {
      return { data: { ...(task.result || {}), cached: Boolean(queued.cached) }, elapsedMs: performance.now() - started, task };
    }
    if (task.status === 'failed') {
      throw new Error(task.error || '任务失败');
    }
    if (task.status === 'canceled') {
      throw new Error('任务已取消');
    }
    onProgress?.(task);
    polls += 1;
    const delay = elapsed < 15000 ? 1500 : Math.min(5000, 2200 + polls * 250);
    await sleep(delay);
  }
}

function App() {
  const [url, setUrl] = useState(defaultPrompt.url);
  const [voices, setVoices] = useState([]);
  const [voiceId, setVoiceId] = useState('my_voice');
  const [rewriteOptions, setRewriteOptions] = useState(DEFAULT_REWRITE_OPTIONS);
  const [rewriteEngine, setRewriteEngine] = useState('ai');
  const [rewriteStyle, setRewriteStyle] = useState('viral');
  const [rewriteTone, setRewriteTone] = useState('natural');
  const [rewriteLength, setRewriteLength] = useState('medium');
  const [rewritePlatform, setRewritePlatform] = useState('douyin');
  const [rewriteStrength, setRewriteStrength] = useState('balanced');
  const [rewriteVariants, setRewriteVariants] = useState(1);
  const [extract, setExtract] = useState({ state: 'idle', message: '' });
  const [rewrite, setRewrite] = useState({ state: 'idle', message: '' });
  const [tts, setTts] = useState({ state: 'idle', message: '' });
  const [voiceUpload, setVoiceUpload] = useState({ state: 'idle', message: '' });
  const [voiceManage, setVoiceManage] = useState({ state: 'idle', message: '' });
  const [voiceNameDraft, setVoiceNameDraft] = useState('');
  const [voicePreview, setVoicePreview] = useState({ state: 'idle', message: '' });
  const [voicePreviewAudio, setVoicePreviewAudio] = useState(null);
  const [ttsSpeed, setTtsSpeed] = useState(1);
  const [videoEdit, setVideoEdit] = useState({ state: 'idle', message: '' });
  const [activeVideoMode, setActiveVideoMode] = useState('moviepy');
  const [videoUpload, setVideoUpload] = useState({ state: 'idle', message: '' });
  const [wav2lip, setWav2lip] = useState({ state: 'idle', message: '' });
  const [storageState, setStorageState] = useState({ state: 'idle', message: '' });
  const [extractedScript, setExtractedScript] = useState('');
  const [segments, setSegments] = useState([]);
  const [finalScript, setFinalScript] = useState('');
  const [audio, setAudio] = useState(null);
  const [defaultBackgroundVideo, setDefaultBackgroundVideo] = useState(FALLBACK_BACKGROUND_VIDEO);
  const [editVideoUrl, setEditVideoUrl] = useState(FALLBACK_BACKGROUND_VIDEO);
  const editRatio = 'vertical';
  const renderPreset = 'balanced';
  const editAddSubtitle = true;
  const useApiSubtitleTiming = false;
  const clipSeconds = 4;
  const subtitleMaxChars = 12;
  const subtitlePosition = 'bottom';
  const subtitleStyle = 'classic';
  const subtitleSize = 'normal';
  const subtitleTextColor = '#ffffff';
  const subtitleBackground = true;
  const [useAllVideos, setUseAllVideos] = useState(true);
  const [uploadedVideos, setUploadedVideos] = useState([]);
  const [renderedVideo, setRenderedVideo] = useState(null);
  const [wav2lipUpload, setWav2lipUpload] = useState({ state: 'idle', message: '' });
  const [wav2lipSourceVideo, setWav2lipSourceVideo] = useState(null);
  const [wav2lipAudioUrl, setWav2lipAudioUrl] = useState('');
  const [wav2lipVideo, setWav2lipVideo] = useState(null);
  const [historyItems, setHistoryItems] = useState([]);
  const [historyCategory, setHistoryCategory] = useState('all');
  const [storageStats, setStorageStats] = useState(null);
  const [usageStats, setUsageStats] = useState(null);
  const [serviceConfig, setServiceConfig] = useState(DEFAULT_SERVICE_CONFIG);
  const [serviceConfigStatus, setServiceConfigStatus] = useState({ state: 'idle', message: '' });
  const [authOpen, setAuthOpen] = useState(false);
  const [authUser, setAuthUser] = useState(null);
  const isAdmin = authUser?.role === 'admin';
  const [authForm, setAuthForm] = useState({ username: '', password: '' });
  const [authStatus, setAuthStatus] = useState({ state: 'idle', message: '' });
  const [adminUsers, setAdminUsers] = useState([]);
  const [adminUsersStatus, setAdminUsersStatus] = useState({ state: 'idle', message: '' });
  const [newUserForm, setNewUserForm] = useState({ username: '', password: '', role: 'user' });
  const isAdminRoute = window.location.pathname.replace(/\/+$/, '') === '/admin';
  const isRealtor = authUser?.role === 'realtor';
  const [realtorForm, setRealtorForm] = useState({
    area: '',
    community: '',
    propertyType: '住宅',
    dealType: '二手房',
    layout: '',
    size: '',
    price: '',
    decoration: '',
    orientation: '',
    floor: '',
    elevator: '',
    metro: '',
    school: '',
    highlights: ['采光好', '户型方正'],
    audience: ['改善家庭'],
    contentDuration: '30秒（约160-220字）',
    style: '成交转化',
    callToAction: '预约看房',
    notes: ''
  });
  const [realtorCopy, setRealtorCopy] = useState({ state: 'idle', message: '' });
  const hasActiveWork = [
    extract,
    rewrite,
    realtorCopy,
    tts,
    voicePreview,
    videoEdit,
    wav2lip
  ].some(item => item.state === 'loading');

  useEffect(() => {
    getJSON('/api/v1/app-config')
      .then(data => {
        const nextDefault = data.default_background_video || FALLBACK_BACKGROUND_VIDEO;
        setDefaultBackgroundVideo(nextDefault);
        setEditVideoUrl(current => current === FALLBACK_BACKGROUND_VIDEO ? nextDefault : current);
      })
      .catch(() => {});

    refreshAuth();
    refreshHistory();
    refreshStorage();
    refreshUsage();

  }, []);

  useEffect(() => {
    refreshVoices();
  }, []);

  useEffect(() => {
    if (!hasActiveWork) return;
    const timer = window.setInterval(() => {
      refreshHistory();
      refreshStorage();
      refreshUsage();
    }, 6000);
    return () => window.clearInterval(timer);
  }, [hasActiveWork]);

  useEffect(() => {
    getJSON('/api/v1/rewrite-options')
      .then(data => setRewriteOptions({
        styles: data.styles?.length ? data.styles : DEFAULT_REWRITE_OPTIONS.styles,
        tones: data.tones?.length ? data.tones : DEFAULT_REWRITE_OPTIONS.tones,
        lengths: data.lengths?.length ? data.lengths : DEFAULT_REWRITE_OPTIONS.lengths,
        platforms: data.platforms?.length ? data.platforms : DEFAULT_REWRITE_OPTIONS.platforms,
        strengths: data.strengths?.length ? data.strengths : DEFAULT_REWRITE_OPTIONS.strengths
      }))
      .catch(() => setRewriteOptions(DEFAULT_REWRITE_OPTIONS));
  }, []);

  const selectedVoice = useMemo(
    () => voices.find(v => v.id === voiceId),
    [voices, voiceId]
  );

  useEffect(() => {
    setVoiceNameDraft(selectedVoice?.name || '');
  }, [selectedVoice?.id, selectedVoice?.name]);

  useEffect(() => {
    setVoicePreview({ state: 'idle', message: '' });
    setVoicePreviewAudio(null);
  }, [voiceId]);

  useEffect(() => {
    setVoicePreview({ state: 'idle', message: '' });
    setVoicePreviewAudio(null);
    setTts({ state: 'idle', message: '' });
    setAudio(null);
    setRenderedVideo(null);
  }, [ttsSpeed]);

  useEffect(() => {
    if (audio?.audio_url && !wav2lipAudioUrl) {
      setWav2lipAudioUrl(audio.audio_url);
    }
  }, [audio, wav2lipAudioUrl]);

  const selectedStyle = useMemo(
    () => rewriteOptions.styles.find(item => item.id === rewriteStyle) || rewriteOptions.styles[0],
    [rewriteOptions.styles, rewriteStyle]
  );

  const selectedRatio = useMemo(
    () => VIDEO_RATIOS.find(item => item.id === editRatio) || VIDEO_RATIOS[0],
    [editRatio]
  );

  const selectedRenderPreset = useMemo(
    () => VIDEO_RENDER_PRESETS.find(item => item.id === renderPreset) || VIDEO_RENDER_PRESETS[0],
    [renderPreset]
  );

  const renderVideoSources = useMemo(() => {
    if (useAllVideos && uploadedVideos.length) {
      return uploadedVideos.map(video => video.video_url);
    }
    const source = editVideoUrl.trim();
    return source ? [source] : [];
  }, [editVideoUrl, uploadedVideos, useAllVideos]);

  const previewVideoSource = useMemo(() => {
    const uploadedPreview = uploadedVideos[0]?.preview_url;
    if (uploadedPreview) return withAuthQuery(uploadedPreview);
    const source = editVideoUrl.trim();
    return PREVIEWABLE_MEDIA_RE.test(source) ? withAuthQuery(source) : '';
  }, [editVideoUrl, uploadedVideos]);

  const effectiveSubtitleTextColor = useMemo(() => {
    if (subtitleStyle === 'yellow' && subtitleTextColor === '#ffffff') {
      return '#ffe650';
    }
    return subtitleTextColor;
  }, [subtitleStyle, subtitleTextColor]);

  const subtitlePreviewText = useMemo(() => {
    const source = (finalScript || extractedScript || '字幕预览会根据字数自动换行方便你调整样式').trim();
    return wrapPreviewCaption(source, subtitleMaxChars);
  }, [extractedScript, finalScript, subtitleMaxChars]);

  const metrics = useMemo(() => ({
    sourceChars: extractedScript.length || 0,
    rewriteChars: finalScript.length || 0,
    segments: segments.length || 0,
    audioDuration: audio?.duration_sec ? `${audio.duration_sec}s` : '-'
  }), [extractedScript, finalScript, segments, audio]);

  const historyCategoryCounts = useMemo(() => {
    const counts = { all: historyItems.length, video: 0, wav2lip: 0, tts: 0, script: 0, active: 0, failed: 0 };
    historyItems.forEach(item => {
      const category = historyItemCategory(item);
      if (Object.prototype.hasOwnProperty.call(counts, category)) {
        counts[category] += 1;
      }
    });
    return counts;
  }, [historyItems]);

  const visibleHistoryItems = useMemo(() => {
    if (historyCategory === 'all') return historyItems;
    return historyItems.filter(item => historyItemCategory(item) === historyCategory);
  }, [historyCategory, historyItems]);

  const taskStatus = storageStats?.task_status || {};
  const queuedTasks = Number(taskStatus.queued || 0);
  const runningTasks = Number(taskStatus.running || 0);
  const failedTasks = Number(taskStatus.failed || 0);
  const workerStatus = storageStats?.jobs || {};
  const workerLabel = workerStatus.backend === 'celery'
    ? `${workerStatus.active || 0}/${workerStatus.workers || 0}`
    : `${workerStatus.running || 0}/${workerStatus.max_workers || 0}`;
  const queueLabel = `${runningTasks} 运行 · ${queuedTasks} 排队`;

  async function refreshHistory() {
    try {
      const data = await getJSON(`/api/v1/history?limit=${HISTORY_LIMIT}`);
      setHistoryItems((data.tasks || []).filter(item => !HIDDEN_HISTORY_PREFIXES.some(prefix => item.kind?.startsWith(prefix))));
    } catch {
      setHistoryItems([]);
    }
  }

  async function refreshStorage() {
    try {
      const data = await getJSON('/api/v1/storage');
      setStorageStats(data);
    } catch {
      setStorageStats(null);
    }
  }

  async function refreshUsage() {
    try {
      const data = await getJSON('/api/v1/usage/me');
      setUsageStats(data.usage || null);
    } catch {
      setUsageStats(null);
    }
  }

  async function refreshServiceConfig(user = authUser) {
    try {
      if (user?.role !== 'admin') {
        setServiceConfig(DEFAULT_SERVICE_CONFIG);
        return;
      }
      const data = await getJSON('/api/v1/service-config');
      setServiceConfig({ ...DEFAULT_SERVICE_CONFIG, ...(data.config || {}) });
    } catch {
      setServiceConfig(DEFAULT_SERVICE_CONFIG);
    }
  }

  async function refreshAuth() {
    if (!getAuthToken()) {
      setAuthUser(null);
      setServiceConfig(DEFAULT_SERVICE_CONFIG);
      return;
    }
    try {
      const data = await getJSON('/api/v1/auth/me');
      const user = data.user || null;
      setAuthUser(user);
      await refreshServiceConfig(user);
      if (user?.role === 'admin') {
        await refreshAdminUsers();
      }
    } catch {
      setAuthToken('');
      setAuthUser(null);
      setServiceConfig(DEFAULT_SERVICE_CONFIG);
    }
  }

  function updateAuthForm(key, value) {
    setAuthForm(prev => ({ ...prev, [key]: value }));
    setAuthStatus({ state: 'idle', message: '' });
  }

  async function submitAuth() {
    const username = authForm.username.trim();
    const password = authForm.password;
    if (!username || !password) {
      setAuthStatus({ state: 'error', message: '请输入用户名和密码' });
      return;
    }
    setAuthStatus({ state: 'loading', message: '正在登录' });
    try {
      const { data } = await postJSON('/api/v1/auth/login', { username, password });
      setAuthToken(data.token || '');
      setAuthUser(data.user || null);
      setAuthForm({ username: '', password: '' });
      setAuthStatus({ state: 'done', message: '登录成功' });
      setAuthOpen(false);
      await refreshServiceConfig(data.user || null);
      if (data.user?.role === 'admin') {
        await refreshAdminUsers();
      }
      await refreshVoices(voiceId);
      await refreshUsage();
    } catch (err) {
      setAuthStatus({ state: 'error', message: err.message });
    }
  }

  function logout() {
    setAuthToken('');
    setAuthUser(null);
    setServiceConfig(DEFAULT_SERVICE_CONFIG);
    setAdminUsers([]);
    setAuthStatus({ state: 'idle', message: '' });
    refreshVoices('default');
    setUsageStats(null);
  }

  function updateServiceConfig(section, key, value) {
    setServiceConfig(prev => ({
      ...prev,
      [section]: {
        ...(prev[section] || DEFAULT_SERVICE_CONFIG[section] || {}),
        [key]: value
      }
    }));
    setServiceConfigStatus({ state: 'idle', message: '' });
  }

  async function saveServiceConfig() {
    if (!isAdmin) {
      setServiceConfigStatus({ state: 'error', message: '需要管理员权限' });
      return;
    }
    setServiceConfigStatus({ state: 'loading', message: '正在保存接口配置' });
    try {
      const data = await putJSON('/api/v1/service-config', serviceConfig);
      setServiceConfig({ ...DEFAULT_SERVICE_CONFIG, ...(data.config || {}) });
      setServiceConfigStatus({ state: 'done', message: '接口配置已保存' });
    } catch (err) {
      setServiceConfigStatus({ state: 'error', message: err.message });
    }
  }

  async function refreshAdminUsers() {
    try {
      const data = await getJSON('/api/v1/admin/users?limit=200');
      setAdminUsers(data.users || []);
      setAdminUsersStatus(prev => prev.state === 'loading' ? { state: 'idle', message: '' } : prev);
    } catch (err) {
      setAdminUsers([]);
      setAdminUsersStatus({ state: 'error', message: err.message });
    }
  }

  function updateNewUserForm(key, value) {
    setNewUserForm(prev => ({ ...prev, [key]: value }));
    setAdminUsersStatus({ state: 'idle', message: '' });
  }

  async function createAdminUser() {
    const username = newUserForm.username.trim();
    const password = newUserForm.password;
    if (!username || !password) {
      setAdminUsersStatus({ state: 'error', message: '请输入用户名和密码' });
      return;
    }
    setAdminUsersStatus({ state: 'loading', message: '正在新增用户' });
    try {
      await postJSON('/api/v1/admin/users', { username, password, role: newUserForm.role });
      setNewUserForm({ username: '', password: '', role: 'user' });
      await refreshAdminUsers();
      setAdminUsersStatus({ state: 'done', message: '用户已新增' });
    } catch (err) {
      setAdminUsersStatus({ state: 'error', message: err.message });
    }
  }

  async function deleteAdminUser(user) {
    if (!user?.id) return;
    if (!window.confirm(`确定删除用户「${user.username}」吗？`)) return;
    setAdminUsersStatus({ state: 'loading', message: '正在删除用户' });
    try {
      await deleteJSON(`/api/v1/admin/users/${encodeURIComponent(user.id)}`);
      await refreshAdminUsers();
      setAdminUsersStatus({ state: 'done', message: '用户已删除' });
    } catch (err) {
      setAdminUsersStatus({ state: 'error', message: err.message });
    }
  }

  async function refreshVoices(preferredId = voiceId) {
    try {
      const data = await getJSON('/api/v1/voices');
      const nextVoices = data.voices || [];
      setVoices(nextVoices);
      const preferred = nextVoices.find(v => v.id === preferredId)
        || nextVoices.find(v => v.id === 'my_voice')
        || nextVoices[0];
      if (preferred) setVoiceId(preferred.id);
      else setVoiceId('default');
    } catch {
      setVoices([]);
      setVoiceId('default');
    }
  }

  function progressMessage(prefix, task) {
    const percent = Number(task?.progress || 0);
    const message = task?.message || prefix;
    if (task?.status === 'queued') {
      return '已进入队列，前面有任务时会自动等待';
    }
    if (task?.status === 'running' && /TTS|配音|样音|语音/.test(`${prefix}${message}`)) {
      return `${message}${percent ? `，${percent}%` : ''}，外部声音克隆可能需要 1-3 分钟`;
    }
    return `${message}${percent ? `，${percent}%` : ''}`;
  }

  async function handleExtract() {
    const payload = { reference_url: url.trim(), model: 'base' };

    if (!payload.reference_url) {
      setExtract({ state: 'error', message: '请输入视频链接' });
      return;
    }

    setExtract({ state: 'loading', message: '正在提取文案' });
    try {
      const { data, elapsedMs } = await runBackgroundJob(
        '/api/v1/extract/start',
        payload,
        task => setExtract({ state: 'loading', message: progressMessage('正在提取文案', task) }),
        { timeoutMs: 5 * 60 * 1000 }
      );
      setExtractedScript(data.extracted_script || '');
      setSegments(data.segments || []);
      setExtract({
        state: 'done',
        message: `提取完成，${(data.extracted_script || '').length} 字，${asSeconds(elapsedMs)}。下一步：到模块 2 生成新文案`
      });
      setRewrite({ state: 'idle', message: '' });
      setTts({ state: 'idle', message: '' });
      setVideoEdit({ state: 'idle', message: '' });
      setVideoUpload({ state: 'idle', message: '' });
      setAudio(null);
      setRenderedVideo(null);
      refreshHistory();
      refreshStorage();
      refreshUsage();
    } catch (err) {
      setExtract({ state: 'error', message: err.message });
    }
  }

  async function handleRewrite() {
    const source = extractedScript.trim();
    if (!source) {
      setRewrite({ state: 'error', message: '请先提取文案' });
      return;
    }

    setRewrite({
      state: 'loading',
      message: rewriteEngine === 'ai' ? '正在 AI 深度改写，可能需要 30-90 秒' : '正在快速改写'
    });
    try {
      const { data, elapsedMs } = await runBackgroundJob(
        '/api/v1/rewrite/start',
        {
          reference_text: source,
          rewrite_engine: rewriteEngine,
          rewrite_style: rewriteStyle,
          rewrite_tone: rewriteTone,
          rewrite_length: rewriteLength,
          rewrite_platform: rewritePlatform,
          rewrite_strength: rewriteStrength,
          rewrite_variants: rewriteVariants
        },
        task => setRewrite({ state: 'loading', message: progressMessage('正在改写文案', task) }),
        { timeoutMs: 4 * 60 * 1000 }
      );
      const text = normalizeScriptText(data.final_script || '');
      if (!text) {
        throw new Error('改写接口未返回有效文案');
      }
      setFinalScript(text);
      setRewrite({
        state: 'done',
        message: `改写完成，${text.length} 字，${asSeconds(elapsedMs)}。下一步：到模块 3 生成配音`
      });
      setTts({ state: 'idle', message: '' });
      setVideoEdit({ state: 'idle', message: '' });
      setVideoUpload({ state: 'idle', message: '' });
      setAudio(null);
      setRenderedVideo(null);
    } catch (err) {
      setRewrite({ state: 'error', message: err.message });
    }
  }

  function updateRealtorForm(key, value) {
    setRealtorForm(prev => ({ ...prev, [key]: value }));
    setRealtorCopy({ state: 'idle', message: '' });
  }

  async function handleRealtorGenerate() {
    const source = buildRealtorSource(realtorForm);
    const realtorContext = buildRealtorContext(realtorForm);
    const durationMeta = REALTOR_DURATION_META[realtorForm.contentDuration] || REALTOR_DURATION_META['30秒（约160-220字）'];
    if (!realtorForm.community.trim() && !(realtorForm.highlights || []).length) {
      setRealtorCopy({ state: 'error', message: '请填写楼盘或核心卖点' });
      return;
    }
    setRealtorCopy({ state: 'loading', message: '正在生成房产文案' });
    try {
      const { data, elapsedMs } = await runBackgroundJob(
        '/api/v1/rewrite/start',
        {
          reference_text: source,
          realtor_context: realtorContext,
          rewrite_engine: 'ai',
          rewrite_style: 'sales',
          rewrite_tone: 'professional',
          rewrite_length: durationMeta.rewriteLength,
          rewrite_platform: 'douyin',
          rewrite_strength: 'heavy',
          rewrite_variants: 1
        },
        task => setRealtorCopy({ state: 'loading', message: progressMessage('正在生成房产文案', task) }),
        { timeoutMs: 4 * 60 * 1000 }
      );
      const text = normalizeScriptText(data.final_script || '');
      if (!text) {
        throw new Error('文案生成接口未返回有效内容');
      }
      setExtractedScript(source);
      setSegments([]);
      setFinalScript(text);
      setRealtorCopy({ state: 'done', message: `文案已生成，${text.length} 字，${asSeconds(elapsedMs)}` });
      setTts({ state: 'idle', message: '' });
      setVideoEdit({ state: 'idle', message: '' });
      setVideoUpload({ state: 'idle', message: '' });
      setAudio(null);
      setRenderedVideo(null);
      refreshHistory();
      refreshUsage();
    } catch (err) {
      setRealtorCopy({ state: 'error', message: err.message });
    }
  }

  async function handleTts() {
    const text = finalScript.trim();
    if (!text) {
      setTts({ state: 'error', message: '请先生成改写文案' });
      return;
    }

    const payload = {
      text,
      speed: Number(ttsSpeed) || 1
    };
    if (selectedVoice?.id) {
      payload.voice_id = selectedVoice.id;
    }
    if (selectedVoice?.ref_wav) {
      payload.voice_ref_wav = selectedVoice.ref_wav;
    }

    setTts({ state: 'loading', message: '正在生成配音' });
    try {
      const { data, elapsedMs } = await runBackgroundJob(
        '/api/v1/tts/start',
        payload,
        task => setTts({ state: 'loading', message: progressMessage('正在生成配音', task) }),
        { timeoutMs: 6 * 60 * 1000 }
      );
      const audioUrl = withAuthQuery(withCacheBust(previewAudioUrl(data)));
      const duration = await readAudioDuration(audioUrl);
      const nextAudio = {
        ...data,
        text: data.text || text,
        audio_url: audioUrl,
        duration_sec: duration ? Number(duration.toFixed(2)) : null
      };
      setAudio(nextAudio);
      setTts({
        state: 'done',
        message: `配音完成，${duration ? `${duration.toFixed(2)} 秒，` : ''}语速 ${Number(ttsSpeed).toFixed(1)}x，${asSeconds(elapsedMs)}。下一步：到模块 4 生成视频`
      });
      setVideoEdit({ state: 'idle', message: '' });
      setRenderedVideo(null);
      refreshHistory();
      refreshStorage();
      refreshUsage();
    } catch (err) {
      setTts({ state: 'error', message: err.message });
    }
  }

  function handleVoiceReferencePreview() {
    if (!selectedVoice?.ref_wav) {
      setVoicePreview({
        state: 'error',
        message: selectedVoice?.kind === 'builtin' ? '内置音色没有原始参考录音' : '请先选择音色'
      });
      return;
    }
      setVoicePreviewAudio({
        title: '原音试听',
        audio_url: withAuthQuery(`/api/v1/voices/${encodeURIComponent(selectedVoice.id)}/audio?t=${Date.now()}`)
      });
    setVoicePreview({ state: 'done', message: '正在播放音色原始参考录音' });
  }

  async function handleVoiceSamplePreview() {
    if (!selectedVoice?.ref_wav) {
      setVoicePreview({ state: 'error', message: '当前音色缺少参考录音' });
      return;
    }

    const safeVoiceId = (selectedVoice.id || 'default').replace(/[^a-zA-Z0-9_-]/g, '') || 'default';
    const safeUserId = (authUser?.id || 'local').replace(/[^a-zA-Z0-9_-]/g, '') || 'local';
    const speedLabel = String(Number(ttsSpeed) || 1).replace('.', 'p');
    const sampleTaskId = `voice_sample_${safeUserId}_${safeVoiceId}_${speedLabel}x`;
    const sampleAudioUrl = `/api/v1/audio/${sampleTaskId}`;

    const payload = {
      taskId: sampleTaskId,
      text: '大家好，这是当前音色的试听效果。请听一下声音是否清晰自然，语气是否符合你的口播风格。',
      speed: Number(ttsSpeed) || 1,
      voice_id: selectedVoice.id,
      voice_ref_wav: selectedVoice.ref_wav
    };

    setVoicePreview({ state: 'loading', message: '正在检查试听样音' });
    try {
      const { data, elapsedMs } = await runBackgroundJob(
        '/api/v1/tts/sample/start',
        payload,
        task => setVoicePreview({ state: 'loading', message: progressMessage('正在生成试听样音', task) }),
        { timeoutMs: 6 * 60 * 1000 }
      );
      setVoicePreviewAudio({
        title: '样音试听',
        audio_url: withAuthQuery(withCacheBust(previewAudioUrl(data) || sampleAudioUrl))
      });
      setVoicePreview({
        state: 'done',
        message: data.cached
          ? '已载入已保存的试听样音'
          : `试听样音已生成并保存，语速 ${Number(ttsSpeed).toFixed(1)}x，${asSeconds(elapsedMs)}`
      });
      refreshHistory();
      refreshStorage();
      refreshUsage();
    } catch (err) {
      setVoicePreview({ state: 'error', message: err.message });
    }
  }

  async function handleVoiceImport(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    const allowed = /\.(wav|mp3|m4a|aac|flac|ogg|webm)$/i.test(file.name);
    if (!file.type.startsWith('audio/') && !file.type.startsWith('video/') && !allowed) {
      setVoiceUpload({ state: 'error', message: `${file.name} 不是支持的录音文件` });
      return;
    }

    const started = performance.now();
    const form = new FormData();
    form.append('file', file);
    setVoiceUpload({ state: 'loading', message: '正在导入录音并新增音色' });
    try {
      const res = await fetch(`${API_BASE}/api/v1/upload-voice`, {
        method: 'POST',
        headers: authHeaders(),
        body: form
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `音色导入失败：${res.status}`);
      }
      await refreshVoices(data.voice?.id || 'my_voice');
      setTts({ state: 'idle', message: '' });
      setAudio(null);
      setVoicePreview({ state: 'idle', message: '' });
      setVoicePreviewAudio(null);
      setVoiceUpload({
        state: 'done',
        message: `已新增音色：${data.voice?.name || data.voice?.id || '新音色'}，${formatBytes(data.size_bytes)}，${asSeconds(performance.now() - started)}`
      });
      refreshStorage();
    } catch (err) {
      setVoiceUpload({ state: 'error', message: err.message });
    }
  }

  async function handleVoiceRename() {
    if (!selectedVoice?.id) {
      setVoiceManage({ state: 'error', message: '请先选择音色' });
      return;
    }
    const name = voiceNameDraft.trim();
    if (!name) {
      setVoiceManage({ state: 'error', message: '音色名称不能为空' });
      return;
    }
    if (name === selectedVoice.name) {
      setVoiceManage({ state: 'idle', message: '' });
      return;
    }
    setVoiceManage({ state: 'loading', message: '正在保存音色名称' });
    try {
      const data = await patchJSON(`/api/v1/voices/${encodeURIComponent(selectedVoice.id)}`, { name });
      await refreshVoices(data.voice?.id || selectedVoice.id);
      setVoiceManage({ state: 'done', message: '音色名称已保存' });
    } catch (err) {
      setVoiceManage({ state: 'error', message: err.message });
    }
  }

  async function handleVoiceDelete() {
    if (!selectedVoice?.id) {
      setVoiceManage({ state: 'error', message: '请先选择音色' });
      return;
    }
    if (!window.confirm(`确定删除音色「${selectedVoice.name || selectedVoice.id}」吗？删除后需要重新导入录音。`)) {
      return;
    }
    setVoiceManage({ state: 'loading', message: '正在删除音色' });
    try {
      await deleteJSON(`/api/v1/voices/${encodeURIComponent(selectedVoice.id)}`);
      setVoicePreview({ state: 'idle', message: '' });
      setVoicePreviewAudio(null);
      setAudio(null);
      setTts({ state: 'idle', message: '' });
      await refreshVoices('my_voice');
      setVoiceManage({ state: 'done', message: '音色已删除' });
      refreshStorage();
    } catch (err) {
      setVoiceManage({ state: 'error', message: err.message });
    }
  }

  async function handleVideoImport(event) {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    if (!files.length) return;

    const invalidFile = files.find(file => {
      const allowed = /\.(mp4|mov|m4v|avi|mkv|webm)$/i.test(file.name);
      return !file.type.startsWith('video/') && !allowed;
    });
    if (invalidFile) {
      setVideoUpload({ state: 'error', message: `${invalidFile.name} 不是支持的视频文件` });
      return;
    }

    const started = performance.now();
    const uploaded = [];
    const failed = [];
    setVideoUpload({ state: 'loading', message: `正在导入 1/${files.length}` });
    try {
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        setVideoUpload({ state: 'loading', message: `正在导入 ${index + 1}/${files.length}：${file.name}` });
        const form = new FormData();
        form.append('file', file);
        try {
          const res = await fetch(`${API_BASE}/api/v1/upload-video`, {
            method: 'POST',
            headers: authHeaders(),
            body: form
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            throw new Error(data.detail || `导入失败：${res.status}`);
          }
          uploaded.push({
            ...data,
            preview_url: withAuthQuery(`${data.video_url}?t=${Date.now()}-${index}`)
          });
        } catch (err) {
          failed.push(`${file.name}：${err.message}`);
        }
      }

      if (!uploaded.length) {
        throw new Error(failed[0] || '视频导入失败');
      }

      const selected = uploaded[0];
      const totalBytes = uploaded.reduce((sum, item) => sum + (item.size_bytes || 0), 0);
      setUploadedVideos(prev => [...uploaded, ...prev]);
      setEditVideoUrl(selected.video_url);
      setUseAllVideos(true);
      setRenderedVideo(null);
      setVideoEdit({ state: 'idle', message: '' });
      setVideoUpload({
        state: failed.length ? 'error' : 'done',
        message: failed.length
          ? `已导入 ${uploaded.length} 个，${failed.length} 个失败`
          : `已导入 ${uploaded.length} 个视频，${formatBytes(totalBytes)}，${asSeconds(performance.now() - started)}`
      });
      refreshStorage();
    } catch (err) {
      setVideoUpload({ state: 'error', message: err.message });
    }
  }

  function selectUploadedVideo(video) {
    setEditVideoUrl(video.video_url);
    setUseAllVideos(false);
    setRenderedVideo(null);
    setVideoEdit({ state: 'idle', message: '' });
  }

  function moveUploadedVideo(index, direction) {
    setUploadedVideos(prev => {
      const nextIndex = index + direction;
      if (nextIndex < 0 || nextIndex >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
      return next;
    });
    setRenderedVideo(null);
    setVideoEdit({ state: 'idle', message: '' });
  }

  async function removeUploadedVideo(filename) {
    try {
      await fetch(`${API_BASE}/api/v1/uploads/${filename}`, { method: 'DELETE', headers: authHeaders() });
    } catch {
      // 本地列表仍然移除，避免坏记录卡在界面里。
    }
    const next = uploadedVideos.filter(video => video.filename !== filename);
    setUploadedVideos(next);
    if (!next.length) {
      setUseAllVideos(true);
      setEditVideoUrl(defaultBackgroundVideo);
    } else if (!next.some(video => video.video_url === editVideoUrl)) {
      setEditVideoUrl(next[0].video_url);
    }
    setRenderedVideo(null);
    setVideoEdit({ state: 'idle', message: '' });
    refreshStorage();
  }

  async function handleLipSyncVideoImport(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    const allowed = /\.(mp4|mov|m4v|avi|mkv|webm)$/i.test(file.name);
    if (!file.type.startsWith('video/') && !allowed) {
      setWav2lipUpload({ state: 'error', message: `${file.name} 不是支持的视频文件` });
      return;
    }

    const started = performance.now();
    const form = new FormData();
    form.append('file', file);
    setWav2lipUpload({ state: 'loading', message: `正在上传人物视频：${file.name}` });
    setWav2lipVideo(null);
    setWav2lip({ state: 'idle', message: '' });

    try {
      const res = await fetch(`${API_BASE}/api/v1/upload-video`, {
        method: 'POST',
        headers: authHeaders(),
        body: form
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `上传失败：${res.status}`);
      }
      setWav2lipSourceVideo({
        ...data,
        preview_url: withAuthQuery(`${data.video_url}?t=${Date.now()}`)
      });
      setWav2lipUpload({
        state: 'done',
        message: `人物视频已上传，${formatBytes(data.size_bytes)}，${asSeconds(performance.now() - started)}`
      });
      refreshStorage();
    } catch (err) {
      setWav2lipUpload({ state: 'error', message: err.message });
    }
  }

  async function handleRenderVideo() {
    const videoSources = renderVideoSources;
    const videoSource = videoSources[0] || editVideoUrl.trim();
    const audioSource = audio?.audio_url;
    if (!videoSources.length) {
      setVideoEdit({ state: 'error', message: '请输入背景视频地址' });
      return;
    }
    if (!audioSource) {
      setVideoEdit({ state: 'error', message: '请先生成配音' });
      return;
    }
    const subtitleText = (finalScript || audio?.text || '').trim();
    const useSubtitleApiTiming = useApiSubtitleTiming || (editAddSubtitle && !subtitleText);

    setVideoEdit({ state: 'loading', message: '正在剪辑合成视频' });
    try {
      const taskId = audio?.task_id ? `${audio.task_id}_moviepy` : `moviepy_${Date.now()}`;
      const normalizedClipSeconds = Math.max(1, Math.min(15, Number(clipSeconds) || 4));
      const normalizedSubtitleMaxChars = Math.max(4, Math.min(42, Number(subtitleMaxChars) || 12));
      const { data, elapsedMs } = await runBackgroundJob(
        '/api/v1/edit-video/start',
        {
          videoUrl: videoSource,
          videoUrls: videoSources,
          audioUrl: audioSource,
          taskId,
          subtitle: editAddSubtitle ? subtitleText : '',
          options: {
            loopVideo: true,
            addSubtitle: editAddSubtitle,
            subtitleMode: 'sentence',
            subtitleTiming: useSubtitleApiTiming ? 'api' : 'estimated',
            subtitlePosition,
            subtitleStyle,
            subtitleSize,
            subtitleTextColor: effectiveSubtitleTextColor,
            subtitleBackground,
            subtitleMaxChars: normalizedSubtitleMaxChars,
            fps: selectedRenderPreset.fps,
            width: selectedRatio.width,
            height: selectedRatio.height,
            maxClipSeconds: videoSources.length > 1 ? normalizedClipSeconds : 0,
            crf: selectedRenderPreset.crf,
            ffmpegPreset: selectedRenderPreset.ffmpegPreset
          }
        },
        task => setVideoEdit({ state: 'loading', message: progressMessage('正在剪辑合成视频', task) }),
        { timeoutMs: 20 * 60 * 1000 }
      );
      const videoUrl = withAuthQuery(withCacheBust(previewVideoUrl(data)));
      setRenderedVideo({
        ...data,
        video_url: videoUrl,
        subtitle_url: previewSubtitleUrl(data) ? withAuthQuery(withCacheBust(previewSubtitleUrl(data))) : ''
      });
      setVideoEdit({
          state: 'done',
          message: `视频生成完成，${data.source_count || videoSources.length} 个素材${data.segment_count ? `，剪成 ${data.segment_count} 段` : ''}${data.clip_seconds ? `，每段约 ${data.clip_seconds} 秒` : ''}${data.subtitle_count ? `，${data.subtitle_count} 句字幕` : ''}，${data.duration ? `${data.duration} 秒，` : ''}${asSeconds(elapsedMs)}。下一步：到模块 5 预览下载`
      });
      refreshHistory();
      refreshStorage();
      refreshUsage();
    } catch (err) {
      setVideoEdit({ state: 'error', message: err.message });
    }
  }

  async function handleGenerateLipSync() {
    const videoUrl = (wav2lipSourceVideo?.video_url || '').trim();
    const audioUrl = (wav2lipAudioUrl || audio?.audio_url || '').trim();
    if (!videoUrl) {
      setWav2lip({ state: 'error', message: '请先上传人物视频' });
      return;
    }
    if (!audioUrl) {
      setWav2lip({ state: 'error', message: '请先生成或选择配音音频' });
      return;
    }

    setWav2lip({ state: 'loading', message: '正在调用口型同步接口' });
    try {
      const taskId = `wav2lip_${Date.now()}`;
      const { data, elapsedMs } = await runBackgroundJob(
        '/api/v1/wav2lip/start',
        {
          taskId,
          videoUrl,
          audioUrl
        },
        task => setWav2lip({ state: 'loading', message: progressMessage('正在调用口型同步接口', task) }),
        { timeoutMs: 20 * 60 * 1000 }
      );
      const video = withAuthQuery(withCacheBust(previewVideoUrl(data)));
      setWav2lipVideo({ ...data, video_url: video });
      setRenderedVideo({ ...data, video_url: video });
      setWav2lip({ state: 'done', message: `口型同步完成，${asSeconds(elapsedMs)}。下一步：到模块 5 预览下载` });
      refreshHistory();
      refreshStorage();
    } catch (err) {
      setWav2lip({ state: 'error', message: err.message });
    }
  }

  function copyText(value) {
    navigator.clipboard?.writeText(value || '');
  }

  function restoreHistoryItem(item) {
    const result = item.result || {};
    if (item.kind === 'extract' && result.extracted_script) {
      setExtractedScript(result.extracted_script);
      setSegments(result.segments || []);
      setExtract({ state: 'done', message: `已载入历史文案，${result.extracted_script.length} 字` });
    }
    if (item.kind === 'rewrite' && result.final_script) {
      setFinalScript(result.final_script);
      setRewrite({ state: 'done', message: `已载入历史改写，${result.final_script.length} 字` });
    }
    if (item.kind === 'tts' && previewAudioUrl(result)) {
      const nextAudio = {
        ...result,
        text: result.text || finalScript,
        audio_url: withAuthQuery(withCacheBust(previewAudioUrl(result)))
      };
      setAudio(nextAudio);
      setTts({ state: 'done', message: '已载入历史配音' });
    }
    if (item.kind === 'video' && previewVideoUrl(result)) {
      const videoUrl = withAuthQuery(withCacheBust(previewVideoUrl(result)));
      setRenderedVideo({
        ...result,
        video_url: videoUrl,
        subtitle_url: previewSubtitleUrl(result) ? withAuthQuery(withCacheBust(previewSubtitleUrl(result))) : ''
      });
      setVideoEdit({ state: 'done', message: '已载入历史成片' });
    }
    if (item.kind === 'wav2lip' && previewVideoUrl(result)) {
      const videoUrl = withAuthQuery(withCacheBust(previewVideoUrl(result)));
      setWav2lipAudioUrl(result.audio_source_path || '');
      setWav2lipVideo({ ...result, video_url: videoUrl });
      setRenderedVideo({ ...result, video_url: videoUrl });
      setWav2lip({ state: 'done', message: '已载入历史口型同步视频' });
    }
  }

  async function cancelHistoryItem(item) {
    try {
      await postJSON(`/api/v1/tasks/${encodeURIComponent(item.task_id)}/cancel`, {});
      await refreshHistory();
      await refreshUsage();
    } catch (err) {
      setStorageState({ state: 'error', message: err.message });
    }
  }

  async function retryHistoryItem(item) {
    try {
      const { data } = await postJSON(`/api/v1/tasks/${encodeURIComponent(item.task_id)}/retry`, {});
      setStorageState({ state: 'done', message: `已重新提交任务：${data.task_id}` });
      await refreshHistory();
      await refreshUsage();
    } catch (err) {
      setStorageState({ state: 'error', message: err.message });
    }
  }

  async function handleCleanupTmp() {
    const tmpBytes = storageStats?.tmp?.bytes || 0;
    setStorageState({ state: 'loading', message: '正在清理临时文件' });
    try {
      const { data, elapsedMs } = await postJSON('/api/v1/storage/cleanup', {
        older_than_hours: 0,
        include_tmp: true,
        include_outputs: false,
        include_uploads: false
      });
      await refreshStorage();
      const cleanup = data.cleanup || {};
      const freedBytes = cleanup.bytes_deleted ?? tmpBytes;
      const deletedFiles = cleanup.deleted_files || 0;
      const deletedDirs = cleanup.deleted_dirs || 0;
      const deletedText = deletedFiles || deletedDirs
        ? `删除 ${deletedFiles} 个文件${deletedDirs ? `、${deletedDirs} 个目录` : ''}`
        : '没有可清理的临时文件';
      setStorageState({
        state: 'done',
        message: `${deletedText}，释放 ${formatBytes(freedBytes)}，${asSeconds(elapsedMs)}`
      });
    } catch (err) {
      setStorageState({ state: 'error', message: err.message });
    }
  }

  if (isAdminRoute) {
    return <AdminPage
      authUser={authUser}
      authForm={authForm}
      authStatus={authStatus}
      onAuthChange={updateAuthForm}
      onLogin={submitAuth}
      onLogout={logout}
      serviceConfig={serviceConfig}
      serviceConfigStatus={serviceConfigStatus}
      onConfigChange={updateServiceConfig}
      onConfigSave={saveServiceConfig}
      users={adminUsers}
      usersStatus={adminUsersStatus}
      newUser={newUserForm}
      onNewUserChange={updateNewUserForm}
      onCreateUser={createAdminUser}
      onDeleteUser={deleteAdminUser}
      onRefreshUsers={refreshAdminUsers}
    />;
  }

  return <div className="app-shell">
    <section className="workspace">
      <header className="topbar">
        <div>
          <p className="eyebrow">CosyVoice Video Factory</p>
          <h2>短视频智能生产流水线</h2>
        </div>
        <div className="top-actions">
          {authUser ? (
            <>
              <span className="auth-badge">{authUser.username}{authUser.role !== 'user' ? ` · ${ROLE_LABELS[authUser.role] || authUser.role}` : ''}</span>
              <button className="ghost small" onClick={logout}>退出</button>
            </>
          ) : (
            <button className="ghost small" onClick={() => setAuthOpen(true)}><UserRound size={18}/>登录</button>
          )}
          {isAdmin && (
            <a className="ghost small" href="/admin"><SlidersHorizontal size={18}/>后台管理</a>
          )}
        </div>
      </header>

      <div className="workflow-strip" aria-label="使用顺序">
        <span>使用顺序</span>
        <b>1 提取文案</b>
        <i/>
        <b>2 改写</b>
        <i/>
        <b>3 配音</b>
        <i/>
        <b>4 生成视频</b>
        <i/>
        <b>5 下载</b>
      </div>

    {authOpen && (
      <AuthPanel
        form={authForm}
        status={authStatus}
        onChange={updateAuthForm}
        onSubmit={submitAuth}
        onClose={() => setAuthOpen(false)}
      />
    )}

    <main className="factory-layout">
        {isRealtor ? (
        <Section num="1-2" title="房产文案生成" sub="短视频口播" className="realtor-section" id="realtor-copy">
          <div className="realtor-form">
            <label>
              <span>城市片区</span>
              <input value={realtorForm.area} onChange={e => updateRealtorForm('area', e.target.value)} placeholder="杭州 滨江"/>
            </label>
            <label>
              <span>小区楼盘</span>
              <input value={realtorForm.community} onChange={e => updateRealtorForm('community', e.target.value)} placeholder="江南府"/>
            </label>
            <SelectField label="房源类型" options={REALTOR_OPTIONS.propertyType} value={realtorForm.propertyType} onChange={value => updateRealtorForm('propertyType', value)}/>
            <SelectField label="交易类型" options={REALTOR_OPTIONS.dealType} value={realtorForm.dealType} onChange={value => updateRealtorForm('dealType', value)}/>
            <SelectField label="户型" options={REALTOR_OPTIONS.layout} value={realtorForm.layout} onChange={value => updateRealtorForm('layout', value)}/>
            <SelectField label="面积" options={REALTOR_OPTIONS.size} value={realtorForm.size} onChange={value => updateRealtorForm('size', value)}/>
            <label>
              <span>价格</span>
              <input value={realtorForm.price} onChange={e => updateRealtorForm('price', e.target.value)} placeholder="总价 / 单价 / 预算区间"/>
            </label>
            <SelectField label="装修" options={REALTOR_OPTIONS.decoration} value={realtorForm.decoration} onChange={value => updateRealtorForm('decoration', value)}/>
            <SelectField label="朝向采光" options={REALTOR_OPTIONS.orientation} value={realtorForm.orientation} onChange={value => updateRealtorForm('orientation', value)}/>
            <SelectField label="楼层特点" options={REALTOR_OPTIONS.floor} value={realtorForm.floor} onChange={value => updateRealtorForm('floor', value)}/>
            <SelectField label="梯户" options={REALTOR_OPTIONS.elevator} value={realtorForm.elevator} onChange={value => updateRealtorForm('elevator', value)}/>
            <SelectField label="交通" options={REALTOR_OPTIONS.metro} value={realtorForm.metro} onChange={value => updateRealtorForm('metro', value)}/>
            <SelectField label="教育" options={REALTOR_OPTIONS.school} value={realtorForm.school} onChange={value => updateRealtorForm('school', value)}/>
            <MultiSelectField label="核心卖点" options={REALTOR_OPTIONS.highlights} value={realtorForm.highlights} onChange={value => updateRealtorForm('highlights', value)}/>
            <MultiSelectField label="目标客户" options={REALTOR_OPTIONS.audience} value={realtorForm.audience} onChange={value => updateRealtorForm('audience', value)}/>
            <SelectField label="内容时长" options={REALTOR_OPTIONS.contentDuration} value={realtorForm.contentDuration} onChange={value => updateRealtorForm('contentDuration', value)}/>
            <SelectField label="文案风格" options={REALTOR_OPTIONS.style} value={realtorForm.style} onChange={value => updateRealtorForm('style', value)}/>
            <SelectField label="行动引导" options={REALTOR_OPTIONS.callToAction} value={realtorForm.callToAction} onChange={value => updateRealtorForm('callToAction', value)}/>
            <label className="wide">
              <span>补充信息</span>
              <textarea value={realtorForm.notes} onChange={e => updateRealtorForm('notes', e.target.value)} placeholder="学区、税费、看房时间、业主情况"/>
            </label>
          </div>
          <div className="row-actions realtor-actions">
            <button className="active" onClick={handleRealtorGenerate} disabled={realtorCopy.state === 'loading'}>
              {realtorCopy.state === 'loading' ? <Loader2 size={15}/> : <Wand2 size={15}/>}生成文案
            </button>
            <button onClick={() => copyText(finalScript)}><Copy size={15}/>复制</button>
          </div>
          <StatusLine state={realtorCopy.state} text={realtorCopy.message}/>
          <label>生成结果</label>
          <textarea
            className="script-box textarea-box realtor-output"
            value={finalScript}
            onChange={e => setFinalScript(e.target.value)}
            placeholder="房产口播文案会显示在这里"
          />
        </Section>
        ) : (
        <>
        <Section num="1" title="输入素材" sub="视频链接" className="link-section" id="source">
          <div className="module-help">粘贴视频链接，提取原视频文案。</div>
          <label className="field-label">视频链接 <i>*</i></label>
          <div className="link-input">
            <Link2 size={18}/>
            <input value={url} onChange={e => setUrl(e.target.value)} placeholder="粘贴抖音/B站/快手等视频链接" />
          </div>
          <button className="primary full" onClick={handleExtract} disabled={extract.state === 'loading'}>
            {extract.state === 'loading' ? <Loader2 size={18}/> : <Scissors size={18}/>}开始提取文案
          </button>
          <StatusLine state={extract.state} text={extract.message}/>
          <label>提取结果</label>
          <textarea
            data-script-output
            className="script-box textarea-box"
            value={extractedScript}
            onChange={e => setExtractedScript(e.target.value)}
            placeholder="提取结果会显示在这里"
          />
          <div className="row-actions">
            <button className="active" onClick={handleExtract} disabled={extract.state === 'loading'}>
              <RefreshCcw size={15}/>重新提取
            </button>
            <button onClick={() => copyText(extractedScript)}><Copy size={15}/>复制</button>
          </div>
        </Section>

        <Section num="2" title="AI 改写文案" sub={selectedStyle ? selectedStyle.name : '口播脚本'} className="rewrite-section" id="rewrite">
        <div className="module-help">把提取文案改写成适合短视频口播的新文案。</div>
        <div className="rewrite-config">
          <div className="rewrite-config-head">
            <span><SlidersHorizontal size={15}/>改写风格</span>
            <em>{selectedStyle?.desc || '按所选风格生成'}</em>
          </div>
          <div className="rewrite-tuning">
	            <div>
	              <label>风格</label>
	              <select value={rewriteStyle} onChange={e => setRewriteStyle(e.target.value)}>
	                {rewriteOptions.styles.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </div>
            <div>
              <label>语气</label>
              <select value={rewriteTone} onChange={e => setRewriteTone(e.target.value)}>
                {rewriteOptions.tones.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </div>
	            <div>
	              <label>篇幅</label>
	              <select value={rewriteLength} onChange={e => setRewriteLength(e.target.value)}>
	                {rewriteOptions.lengths.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
	              </select>
	            </div>
	            <div>
	              <label>改写强度</label>
	              <select value={rewriteStrength} onChange={e => setRewriteStrength(e.target.value)}>
	                {rewriteOptions.strengths.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
	              </select>
	            </div>
	          </div>
        </div>
        <textarea
          className="script-box textarea-box rewrite-output"
          value={finalScript}
          onChange={e => setFinalScript(e.target.value)}
          placeholder="改写后的口播文案会显示在这里"
        />
        <div className="row-actions">
          <button
            className="active"
            onClick={handleRewrite}
            disabled={rewrite.state === 'loading' || !extractedScript.trim()}
            title={extractedScript.trim() ? '开始改写提取文案' : '请先提取文案'}
          >
            <Wand2 size={15}/>{extractedScript.trim() ? '生成新文案' : '先提取文案'}
          </button>
          <button onClick={() => copyText(finalScript)}><Copy size={15}/>复制</button>
        </div>
        <StatusLine state={rewrite.state} text={rewrite.message}/>
        <OperationHint show={rewrite.state === 'loading'}>
          AI 改写依赖外部模型，通常 30-90 秒；可以先停留在页面等待结果。
        </OperationHint>
        </Section>
        </>
        )}

        <Section num="3" title="音色设置" sub="接口语音合成" className="voice-section" id="voice">
          <div className="module-help">选择音色，把模块 2 的文案生成配音。</div>
          <div className="voice-grid app-voice-grid">
            <div className="voice-controls">
              <label>
                <span>音色</span>
                <select value={voiceId} onChange={e => setVoiceId(e.target.value)}>
                  {voices.length ? voices.map(v => <option key={v.id} value={v.id}>{v.name}</option>) : <option value="default">默认音色</option>}
                </select>
              </label>
              <label>
                <span>语速</span>
                <select value={ttsSpeed} onChange={e => setTtsSpeed(Number(e.target.value))}>
                  {TTS_SPEED_OPTIONS.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </label>
            </div>
            <div className="audio-card voice-note">
              <p><UserRound size={16}/>当前音色</p>
              <div className="voice-manage-form">
                <div className="voice-name-row">
                  <span className="voice-name-label">名称</span>
                  <input
                    aria-label="音色名称"
                    value={voiceNameDraft}
                    placeholder="给这个音色起个名字"
                    disabled={!selectedVoice?.id || voiceManage.state === 'loading'}
                    onChange={event => {
                      setVoiceNameDraft(event.target.value);
                      setVoiceManage({ state: 'idle', message: '' });
                    }}
                  />
                  <div className="voice-manage-actions">
                    <button
                      type="button"
                      aria-label="保存音色名称"
                      onClick={handleVoiceRename}
                      disabled={!selectedVoice?.id || voiceManage.state === 'loading'}
                      title="保存音色名称"
                    >
                      {voiceManage.state === 'loading' ? <Loader2 size={15}/> : <CheckCircle2 size={15}/>}
                    </button>
                    <button
                      type="button"
                      className="danger"
                      aria-label="删除当前音色"
                      onClick={handleVoiceDelete}
                      disabled={!selectedVoice?.id || voiceManage.state === 'loading'}
                      title="删除当前音色"
                    >
                      <Trash2 size={15}/>
                    </button>
                  </div>
                </div>
              </div>
              <div className="voice-preview-actions">
                <button type="button" onClick={handleVoiceReferencePreview}>
                  <Play size={15}/>试听原音
                </button>
                <button type="button" onClick={handleVoiceSamplePreview} disabled={voicePreview.state === 'loading'}>
                  {voicePreview.state === 'loading' ? <Loader2 size={15}/> : <Volume2 size={15}/>}试听样音
                </button>
              </div>
              {voicePreviewAudio ? (
                <div className="voice-preview-player">
                  <span>{voicePreviewAudio.title}</span>
                  <audio controls src={voicePreviewAudio.audio_url} />
                </div>
              ) : (
                <div className="empty-audio voice-preview-empty">等待试听</div>
              )}
              <label className={`import-video-button voice-import-button ${voiceUpload.state === 'loading' ? 'disabled' : ''}`}>
                {voiceUpload.state === 'loading' ? <Loader2 size={15}/> : <Upload size={15}/>}导入录音
                <input
                  type="file"
                  accept="audio/*,video/webm,.wav,.mp3,.m4a,.aac,.flac,.ogg,.webm"
                  onChange={handleVoiceImport}
                  disabled={voiceUpload.state === 'loading'}
                />
              </label>
            </div>
            <div className="audio-card">
              <p><AudioLines size={16}/>生成结果</p>
              {audio ? <audio controls src={audio.audio_url} /> : <div className="empty-audio">等待生成</div>}
              {audio && <a className="download-link" href={audio.audio_url} download><Download size={15}/>下载音频</a>}
            </div>
          </div>
	          <StatusLine state={voicePreview.state} text={voicePreview.message}/>
          <OperationHint show={voicePreview.state === 'loading'}>
            试听样音会调用外部声音克隆接口，同一音色同一语速生成后会自动复用。
          </OperationHint>
	          <StatusLine state={voiceManage.state} text={voiceManage.message}/>
	          <StatusLine state={voiceUpload.state} text={voiceUpload.message}/>
	          <button className="primary full" onClick={handleTts} disabled={tts.state === 'loading'}>
	            {tts.state === 'loading' ? <Loader2 size={18}/> : <Mic2 size={18}/>}生成配音
	          </button>
	          <StatusLine state={tts.state} text={tts.message}/>
          <OperationHint show={tts.state === 'loading'}>
            配音生成依赖外部 TTS clone 服务，长文案会更慢；排队期间不要重复点击。
          </OperationHint>
	        </Section>

        <Section num="4" title="视频生成" sub="剪辑成片 · 口型同步" className="video-workflow-section" id="moviepy">
          <div className="module-help">导入视频素材，用配音生成成片；需要人物对口型时切换到口型同步。</div>
          <div className="module-switch" role="tablist" aria-label="视频生成模式">
            <button
              type="button"
              className={activeVideoMode === 'moviepy' ? 'active' : ''}
              onClick={() => setActiveVideoMode('moviepy')}
            >
              <Film size={16}/>视频剪辑成片
              <small>素材视频 + 配音生成短视频</small>
            </button>
            <button
              type="button"
              className={activeVideoMode === 'lipsync' ? 'active' : ''}
              onClick={() => setActiveVideoMode('lipsync')}
            >
              <AudioLines size={16}/>口型同步
              <small>人物视频对上配音口型</small>
            </button>
          </div>
          {activeVideoMode === 'moviepy' ? (
            <div className="video-mode-panel moviepy-section">
                        <div className="moviepy-label-row">
                          <label className={`import-video-button ${videoUpload.state === 'loading' ? 'disabled' : ''}`}>
                            {videoUpload.state === 'loading' ? <Loader2 size={15}/> : <Upload size={15}/>}导入视频
                            <input
                              type="file"
                              multiple
                              accept="video/*,.mp4,.mov,.m4v,.avi,.mkv,.webm"
                              onChange={handleVideoImport}
                              disabled={videoUpload.state === 'loading'}
                            />
                          </label>
                          {uploadedVideos.length > 1 && (
                            <label className="toggle-line moviepy-playlist-toggle">
                              <input
                                type="checkbox"
                                checked={useAllVideos}
                                onChange={e => setUseAllVideos(e.target.checked)}
                              />
                              全部轮播
                            </label>
                          )}
                        </div>
                        <StatusLine state={videoUpload.state} text={videoUpload.message}/>
                        {uploadedVideos.length > 0 && (
                          <div className="background-video-list">
                            {uploadedVideos.map((video, index) => (
                              <div
                                className={`background-video-card ${useAllVideos ? 'queued' : editVideoUrl === video.video_url ? 'active' : ''}`}
                                key={video.filename}
                                role="button"
                                tabIndex={0}
                                onClick={() => selectUploadedVideo(video)}
                                onKeyDown={e => {
                                  if (e.key === 'Enter' || e.key === ' ') selectUploadedVideo(video);
                                }}
                              >
                                <video muted playsInline preload="metadata" src={withAuthQuery(video.preview_url)} />
                                <div className="background-card-actions">
                                  <button
                                    type="button"
                                    title="上移"
                                    disabled={index === 0}
                                    onClick={e => {
                                      e.stopPropagation();
                                      moveUploadedVideo(index, -1);
                                    }}
                                  >
                                    <ArrowUp size={14}/>
                                  </button>
                                  <button
                                    type="button"
                                    title="下移"
                                    disabled={index === uploadedVideos.length - 1}
                                    onClick={e => {
                                      e.stopPropagation();
                                      moveUploadedVideo(index, 1);
                                    }}
                                  >
                                    <ArrowDown size={14}/>
                                  </button>
                                  <button
                                    type="button"
                                    title="删除"
                                    onClick={e => {
                                      e.stopPropagation();
                                      removeUploadedVideo(video.filename);
                                    }}
                                  >
                                    <Trash2 size={14}/>
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                        {useAllVideos && uploadedVideos.length > 1 && (
                          <div className="moviepy-playlist-summary">{uploadedVideos.length} 个背景视频将自动取段铺满，每段约 {clipSeconds || 4} 秒</div>
                        )}
                        <label>当前配音</label>
                        <div className="path-box moviepy-audio-source">{audio?.audio_path || audio?.audio_url || '等待配音'}</div>
	                        <button className="primary full" onClick={handleRenderVideo} disabled={videoEdit.state === 'loading'}>
	                          {videoEdit.state === 'loading' ? <Loader2 size={18}/> : <Film size={18}/>}生成视频
	                        </button>
	                        <StatusLine state={videoEdit.state} text={videoEdit.message}/>
                        <OperationHint show={videoEdit.state === 'loading'}>
                          视频合成会上传素材并等待外部剪辑服务返回，较长视频可能需要几分钟。
                        </OperationHint>
	            </div>
          ) : (
            <div className="video-mode-panel wav2lip-section" id="lipsync">
                        <label>人物视频</label>
                        <div className="wav2lip-upload-row">
                          <label className={`import-video-button ${wav2lipUpload.state === 'loading' ? 'disabled' : ''}`}>
                            {wav2lipUpload.state === 'loading' ? <Loader2 size={15}/> : <Upload size={15}/>}
                            {wav2lipSourceVideo ? '更换人物视频' : '上传人物视频'}
                            <input
                              type="file"
                              accept="video/*,.mp4,.mov,.m4v,.avi,.mkv,.webm"
                              onChange={handleLipSyncVideoImport}
                              disabled={wav2lipUpload.state === 'loading'}
                            />
                          </label>
                          {wav2lipSourceVideo && (
                            <button
                              type="button"
                              className="outline wav2lip-clear-button"
                              onClick={() => {
                                setWav2lipSourceVideo(null);
                                setWav2lipVideo(null);
                                setWav2lipUpload({ state: 'idle', message: '' });
                              }}
                            >
                              <Trash2 size={14}/>移除
                            </button>
                          )}
                        </div>
                        <StatusLine state={wav2lipUpload.state} text={wav2lipUpload.message}/>
                        {wav2lipSourceVideo && (
                          <div className="wav2lip-source-card">
                            <video muted playsInline controls preload="metadata" src={withAuthQuery(wav2lipSourceVideo.preview_url || wav2lipSourceVideo.video_url)} />
                            <span>{formatBytes(wav2lipSourceVideo.size_bytes)}</span>
                          </div>
                        )}
                        <label>配音音频</label>
                        <input
                          className="text-input"
                          value={wav2lipAudioUrl}
                          onChange={e => setWav2lipAudioUrl(e.target.value)}
                          placeholder="默认使用模块 3 生成的配音"
                        />
	                        <button className="primary full" onClick={handleGenerateLipSync} disabled={wav2lip.state === 'loading'}>
	                          {wav2lip.state === 'loading' ? <Loader2 size={18}/> : <AudioLines size={18}/>}生成口型同步
	                        </button>
	                        <StatusLine state={wav2lip.state} text={wav2lip.message}/>
                        <OperationHint show={wav2lip.state === 'loading'}>
                          口型同步是重任务，建议等待完成后再发起下一次生成。
                        </OperationHint>
	                        <div className="wav2lip-target-note">
                          <AudioLines size={18}/>
                          <span>{wav2lipVideo ? '口型同步视频已生成，请在模块 5 预览和下载' : '生成后的口型同步视频会显示在模块 5'}</span>
                        </div>
            </div>
          )}
        </Section>

        <Section num="5" title="成片预览" sub="视频下载" className="result-section" id="result">
          <div className="module-help">预览并下载最终视频。</div>
          {renderedVideo ? (
            <div className="video-result-card">
              <video controls src={renderedVideo.video_url} />
              <a className="download-link" href={renderedVideo.video_url} download>
                <Download size={15}/>下载视频
              </a>
              {renderedVideo.subtitle_url && (
                <a className="download-link" href={renderedVideo.subtitle_url} download>
                  <FileText size={15}/>下载字幕
                </a>
              )}
            </div>
          ) : (
            <div className="video-result-card preview-result-card">
              <div className={`subtitle-preview-frame result-preview-frame ratio-${editRatio}`}>
                {previewVideoSource ? (
                  <video muted playsInline loop preload="metadata" src={previewVideoSource} />
                ) : (
                  <div className="subtitle-preview-placeholder"><Film size={18}/><span>预览画面</span></div>
                )}
                <div
                  className={`subtitle-preview-caption pos-${subtitlePosition} style-${subtitleStyle} size-${subtitleSize} ${subtitleBackground ? '' : 'no-bg'} ${editAddSubtitle ? '' : 'off'}`}
                  style={{ '--subtitle-preview-color': effectiveSubtitleTextColor }}
                >
                  {editAddSubtitle ? subtitlePreviewText : '字幕已关闭'}
                </div>
              </div>
            </div>
          )}
	        </Section>

        <Section num="6" title="作品记录" sub="历史与存储" className="history-section" id="history">
          <div className="module-help">查看历史作品，恢复到页面后继续预览或下载。</div>
          <div className="storage-card">
            <div>
              <p><Database size={15}/>本地存储</p>
              <strong>{storageStats ? formatBytes(storageStats.total_bytes) : '-'}</strong>
              <span>{storageStats ? `临时 ${formatBytes(storageStats.tmp?.bytes || 0)} · 共 ${storageStats.total_files || 0} 个文件` : '正在读取'}</span>
            </div>
            <button type="button" onClick={handleCleanupTmp} disabled={storageState.state === 'loading'}>
              {storageState.state === 'loading' ? <Loader2 size={14}/> : <Trash2 size={14}/>}清临时
            </button>
          </div>
          <StatusLine state={storageState.state} text={storageState.message}/>
          <div className="usage-grid">
            <div className="usage-card">
              <span>我的作品</span>
              <strong>{usageStats ? usageStats.task_count : '-'}</strong>
            </div>
            <div className="usage-card">
              <span>上传占用</span>
              <strong>{usageStats ? formatBytes(usageStats.upload_bytes || 0) : '-'}</strong>
            </div>
	            <div className="usage-card">
	              <span>本地队列</span>
	              <strong>{storageStats?.jobs ? workerLabel : '-'}</strong>
              <em>{storageStats ? queueLabel : '正在读取'}</em>
	            </div>
            <div className={`usage-card ${queuedTasks || runningTasks ? 'busy' : ''}`}>
              <span>生成状态</span>
              <strong>{queuedTasks || runningTasks ? `${runningTasks + queuedTasks} 个处理中` : '空闲'}</strong>
              <em>{failedTasks ? `${failedTasks} 个失败任务可重试` : '没有等待任务'}</em>
	            </div>
	          </div>
          <div className="history-filter">
            {HISTORY_CATEGORIES.map(category => (
              <button
                type="button"
                key={category.id}
                className={historyCategory === category.id ? 'active' : ''}
                onClick={() => setHistoryCategory(category.id)}
              >
                {category.label}
                <span>{historyCategoryCounts[category.id] || 0}</span>
              </button>
            ))}
          </div>
          <div className="history-summary">
            显示 {visibleHistoryItems.length} / {historyItems.length} 条
          </div>
          <div className="history-list">
            {visibleHistoryItems.length ? visibleHistoryItems.map(item => (
              <div className="history-item" key={item.task_id}>
                <div>
                  <p><History size={14}/>{item.title || item.kind}</p>
                  <span>{item.status === 'success' ? '完成' : item.status} · {item.task_id}</span>
                </div>
                <div className="history-actions">
                  <button type="button" onClick={() => restoreHistoryItem(item)} disabled={item.status !== 'success'}>
                    恢复到页面
                  </button>
                  {item.status === 'queued' && (
                    <button type="button" onClick={() => cancelHistoryItem(item)}>
                      取消
                    </button>
                  )}
                  {(item.status === 'failed' || item.status === 'canceled') && (
                    <button type="button" onClick={() => retryHistoryItem(item)}>
                      重试
                    </button>
                  )}
                </div>
              </div>
            )) : <div className="empty-history">当前分类暂无作品记录</div>}
          </div>
        </Section>

	    </main>
    </section>
  </div>;
}

function readAudioDuration(src) {
  return new Promise(resolve => {
    const audio = new Audio(src);
    audio.addEventListener('loadedmetadata', () => resolve(audio.duration), { once: true });
    audio.addEventListener('error', () => resolve(null), { once: true });
  });
}

createRoot(document.getElementById('root')).render(<App />);
