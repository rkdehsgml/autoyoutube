// Telegram 웹훅 → GitHub repository_dispatch 중계 (Cloudflare Worker, 무료 플랜)
//
// 버튼:  ok|<job_id>|<run_id>  → publish 워크플로 실행
//        no|<job_id>|<run_id>  → 반려(아무것도 올리지 않음)
// 명령:  /new <주제>            → generate 워크플로 실행
//        /help
//
// 필요한 값 (wrangler secret put ...):
//   TG_BOT_TOKEN, TG_WEBHOOK_SECRET, TG_ALLOWED_CHAT_ID, GH_TOKEN
// wrangler.toml [vars]: GH_REPO = "owner/autoyoutube"

const JOB_ID = /^\d{8}-\d{6}-[a-z0-9]{4}$/;
const RUN_ID = /^\d+$/;

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return new Response("ok");
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TG_WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }
    const update = await request.json();
    try {
      if (update.callback_query) await onButton(update.callback_query, env);
      else if (update.message?.text) await onText(update.message, env);
    } catch (err) {
      const chatId = update.callback_query?.message?.chat?.id ?? update.message?.chat?.id;
      if (chatId) await tg(env, "sendMessage", { chat_id: chatId, text: `오류: ${err.message}` });
    }
    return new Response("ok"); // 텔레그램에는 항상 200
  },
};

function allowed(chatId, env) {
  return String(chatId) === String(env.TG_ALLOWED_CHAT_ID);
}

async function onButton(q, env) {
  const chatId = q.message.chat.id;
  if (!allowed(chatId, env)) return;
  const [action, jobId, runId] = (q.data || "").split("|");
  if (!JOB_ID.test(jobId) || !RUN_ID.test(runId)) throw new Error("잘못된 버튼 데이터");

  // 버튼 제거 → 중복 승인 방지
  await tg(env, "editMessageReplyMarkup", {
    chat_id: chatId,
    message_id: q.message.message_id,
    reply_markup: { inline_keyboard: [] },
  });

  if (action === "ok") {
    await dispatch(env, "publish", { job_id: jobId, run_id: runId });
    await tg(env, "answerCallbackQuery", { callback_query_id: q.id, text: "업로드를 시작합니다" });
    await tg(env, "sendMessage", { chat_id: chatId, text: `승인됨: ${jobId}\n업로드가 끝나면 알려드릴게요.` });
  } else {
    await tg(env, "answerCallbackQuery", { callback_query_id: q.id, text: "반려했습니다" });
    await tg(env, "sendMessage", { chat_id: chatId, text: `반려됨: ${jobId}` });
  }
}

async function onText(message, env) {
  const chatId = message.chat.id;
  if (!allowed(chatId, env)) return;
  const text = message.text.trim();

  if (text.startsWith("/new")) {
    const topic = text.replace(/^\/new(@\w+)?/, "").trim();
    if (!topic) {
      await tg(env, "sendMessage", { chat_id: chatId, text: "사용법: /new 장마철 원룸 곰팡이 냄새" });
      return;
    }
    await dispatch(env, "generate", { topic: topic.slice(0, 100) });
    await tg(env, "sendMessage", { chat_id: chatId, text: `생성 시작: ${topic}\n보통 5분 안에 미리보기가 옵니다.` });
    return;
  }
  await tg(env, "sendMessage", {
    chat_id: chatId,
    text: "/new <주제> — 영상 생성\n미리보기의 [승인 · 업로드] 버튼 — 업로드",
  });
}

async function dispatch(env, eventType, payload) {
  const res = await fetch(`https://api.github.com/repos/${env.GH_REPO}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "autotube-approval-worker",
    },
    body: JSON.stringify({ event_type: eventType, client_payload: payload }),
  });
  if (!res.ok) throw new Error(`GitHub dispatch 실패 ${res.status}: ${await res.text()}`);
}

async function tg(env, method, body) {
  const res = await fetch(`https://api.telegram.org/bot${env.TG_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}
