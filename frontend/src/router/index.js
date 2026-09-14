import { createRouter, createWebHistory } from "vue-router";

import HomeView from "../views/HomeView.vue";
import LobbyView from "../views/LobbyView.vue";
import RoomView from "../views/RoomView.vue";
import AdminLoginView from "../views/AdminLoginView.vue";
import AdminView from "../views/AdminView.vue";

const router = createRouter({
  history: createWebHistory(),

  routes: [
    {
      path: "/",
      name: "home",
      component: HomeView,
    },
    {
      path: "/lobby/:roomId",
      name: "lobby",
      component: LobbyView,
    },
    {
      path: "/room/:roomId",
      name: "room",
      component: RoomView,
    },
    {
      path: "/admin/login",
      name: "admin-login",
      component: AdminLoginView,
    },
    {
      path: "/admin",
      name: "admin",
      component: AdminView,
      beforeEnter: () =>
        localStorage.getItem("script_kill_admin_token")
          ? true
          : { name: "admin-login" },
    },
  ],
});

export default router;
