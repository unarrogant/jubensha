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
  <main class="admin-login-page">
    <section class="admin-login-panel" aria-labelledby="admin-login-title">
      <div class="admin-login-mark"><ShieldCheck :size="25" /></div>
      <span class="admin-eyebrow">SCRIPT KILL CONTROL</span>
      <h1 id="admin-login-title">管理后台</h1>
      <p class="admin-login-subtitle">查看运行中的房间与剧本服务状态</p>

      <form class="admin-login-form" @submit.prevent="submit">
        <label>
          <span>管理员账号</span>
          <input v-model="username" autocomplete="username" placeholder="输入账号" />
        </label>
        <label>
          <span>管理员密码</span>
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="输入密码"
          />
        </label>
        <p v-if="errorMessage" class="admin-alert" role="alert">{{ errorMessage }}</p>
        <button class="button button-primary admin-login-button" type="submit" :disabled="loading">
          <LogIn :size="16" />
          {{ loading ? "验证中..." : "登录管理后台" }}
        </button>
      </form>
    </section>
  </main>
</template>

<style scoped>
.admin-login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 28px;
  background: #eef1ee;
}

.admin-login-panel {
  width: min(430px, 100%);
  padding: 38px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-top: 4px solid var(--green);
  border-radius: 6px;
  box-shadow: var(--shadow);
}

.admin-login-mark {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  margin-bottom: 22px;
  color: #fff;
  background: var(--green);
  border-radius: 4px;
}

.admin-eyebrow {
  color: var(--red);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
}

h1 {
  margin: 8px 0 7px;
  font-family: Georgia, "Songti SC", serif;
  font-size: 32px;
  font-weight: 600;
}

.admin-login-subtitle {
  margin-bottom: 28px;
  color: var(--muted);
  font-size: 12px;
}

.admin-login-form {
  display: grid;
  gap: 16px;
}

.admin-login-form label {
  display: grid;
  gap: 7px;
}

.admin-login-form label span {
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
}

.admin-login-button {
  width: 100%;
  margin-top: 4px;
}

.admin-alert {
  margin: 0;
  padding: 10px 12px;
  color: #74272d;
  background: var(--red-soft);
  border: 1px solid #e5bdc0;
  border-radius: 4px;
  font-size: 11px;
}

@media (max-width: 500px) {
  .admin-login-page {
    padding: 16px;
  }

  .admin-login-panel {
    padding: 28px 22px;
  }
}
</style>
