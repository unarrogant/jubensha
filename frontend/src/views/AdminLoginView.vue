<script setup>
import { ref } from "vue";
import { useRouter } from "vue-router";
import { LogIn, ShieldCheck } from "@lucide/vue";
import { adminLogin } from "../services/api";

const router = useRouter();
const username = ref("admin");
const password = ref("");
const loading = ref(false);
const errorMessage = ref("");

async function submit() {
  if (loading.value) return;
  errorMessage.value = "";
  if (!username.value.trim() || !password.value) {
    errorMessage.value = "请输入管理员账号和密码";
    return;
  }

  loading.value = true;
  try {
    const result = await adminLogin(username.value.trim(), password.value);
    localStorage.setItem("script_kill_admin_token", result.access_token);
    localStorage.setItem("script_kill_admin_username", username.value.trim());
    await router.replace("/admin");
  } catch (error) {
    errorMessage.value = error.message || "登录失败，请检查后端服务";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="admin admin-login-page">
    <section class="admin-login-panel" aria-labelledby="admin-login-title">
      <div class="admin-login-mark"><ShieldCheck :size="23" /></div>
      <span class="admin-login-eyebrow">Curtain Between · Ops Console</span>
      <h1 id="admin-login-title">幕间戏语运营台</h1>
      <p class="admin-login-subtitle">房间运行、AI 主持与玩家行为的统一入口</p>

      <form class="admin-login-form" @submit.prevent="submit">
        <label>
          <span>管理员账号</span>
          <input v-model="username" class="admin-login-inp" autocomplete="username" placeholder="输入账号" />
        </label>
        <label>
          <span>管理员密码</span>
          <input
            v-model="password"
            class="admin-login-inp"
            type="password"
            autocomplete="current-password"
            placeholder="输入密码"
          />
        </label>
        <p v-if="errorMessage" class="admin-login-alert" role="alert">{{ errorMessage }}</p>
        <button class="admin-login-submit" type="submit" :disabled="loading">
          <LogIn :size="15" />
          {{ loading ? "验证中..." : "登录管理后台" }}
        </button>
      </form>
    </section>
  </main>
</template>

<style scoped>
.admin-login-page {
  display: grid;
  grid-template-columns: 1fr;
  place-items: center;
  height: 100vh;
  padding: 28px;
}

.admin-login-panel {
  width: min(420px, 100%);
  padding: 34px 32px 30px;
  border: 1px solid var(--line);
  border-radius: var(--r);
  background: var(--panel);
}

.admin-login-mark {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  margin-bottom: 20px;
  color: var(--acc-soft);
  background: var(--acc-dim);
  border: 1px solid var(--acc-line);
  border-radius: 12px;
}

.admin-login-eyebrow {
  font-size: 10.5px;
  letter-spacing: .24em;
  text-transform: uppercase;
  color: var(--faint);
}

.admin-login-panel h1 {
  margin: 10px 0 6px;
  font-family: var(--serif);
  font-size: 26px;
  font-weight: 600;
  color: var(--ink);
}

.admin-login-subtitle {
  margin: 0 0 26px;
  color: var(--muted);
  font-size: 12.5px;
}

.admin-login-form {
  display: grid;
  gap: 16px;
}

.admin-login-form label > span {
  display: block;
  margin-bottom: 7px;
  color: var(--muted);
  font-size: 11.5px;
  letter-spacing: .1em;
}

.admin-login-inp {
  width: 100%;
  padding: 12px 14px;
  color: var(--ink);
  background: rgba(4, 6, 11, .6);
  border: 1px solid var(--line-2);
  border-radius: 11px;
  font-size: 14px;
  transition: .2s;
}

.admin-login-inp:focus {
  border-color: var(--acc);
  box-shadow: 0 0 0 3px var(--acc-dim);
}

.admin-login-alert {
  margin: 0;
  padding: 10px 12px;
  color: #f0a5a5;
  background: rgba(217, 106, 106, .08);
  border: 1px solid rgba(217, 106, 106, .42);
  border-radius: 10px;
  font-size: 12px;
}

.admin-login-submit {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  margin-top: 6px;
  padding: 12px;
  color: #08110f;
  background: var(--acc);
  border-radius: 11px;
  font-size: 14px;
  font-weight: 600;
  transition: .18s var(--ease);
}

.admin-login-submit:hover:not(:disabled) {
  background: var(--acc-soft);
}

.admin-login-submit:disabled {
  opacity: .55;
  cursor: default;
}

@media (max-width: 500px) {
  .admin-login-page {
    padding: 16px;
  }

  .admin-login-panel {
    padding: 26px 20px;
  }
}
</style>
