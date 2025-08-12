import { serve } from "https://deno.land/std/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { v4 as uuidv4 } from "https://esm.sh/uuid@9.0.0";

const H = { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" };
const UNSUB_BASE = "https://corocmnneqzimohtrhuf.supabase.co/functions/v1/unsubscribe";

serve(async (req) => {
  try {
    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
    );

    // 1) 이메일의 "구독하기" 토큰 링크 처리
    if (req.method === "GET") {
      const token = new URL(req.url).searchParams.get("token") ?? "";
      if (!token) {
        return new Response("구독 활성화 링크가 아닙니다. 이메일을 POST로 전송하세요.", { headers: H });
      }

      const { data, error } = await supabase
        .from("subscribers")
        .update({ subscribed: true })
        .eq("token", token)
        .select("email")
        .single();

      if (error || !data) return new Response("잘못된 링크입니다.", { headers: H });
      return new Response(`구독 다시 활성화: ${data.email}`, { headers: H });
    }

    // 2) 폼/API에서 새 구독 등록
    if (req.method === "POST") {
      const ct = req.headers.get("content-type") || "";
      let email = "";

      if (ct.includes("application/json")) {
        const body = await req.json();
        email = (body.email || "").trim().toLowerCase();
      } else if (ct.includes("application/x-www-form-urlencoded")) {
        const body = new URLSearchParams(await req.text());
        email = (body.get("email") || "").trim().toLowerCase();
      } else {
        return new Response("지원하지 않는 Content-Type", { status: 415, headers: H });
      }

      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        return new Response("이메일 형식 오류", { status: 400, headers: H });
      }

      const token = uuidv4();
      const { data, error } = await supabase
        .from("subscribers")
        .upsert({ email, subscribed: true, token }, { onConflict: "email" })
        .select("email, token")
        .single();

      if (error) return new Response("DB 오류", { status: 500, headers: H });

      const t = data?.token ?? token;
      return new Response(
        `구독 완료: ${email}\n구독취소 링크: ${UNSUB_BASE}?token=${t}`,
        { headers: H },
      );
    }

    return new Response("Method Not Allowed", { status: 405, headers: H });
  } catch (e) {
    console.error(e);
    return new Response("서버 오류", { status: 500, headers: H });
  }
});
