import { serve } from "https://deno.land/std/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const H = { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" };

serve(async (req) => {
  try {
    const token = new URL(req.url).searchParams.get("token") ?? "";
    if (!token) return new Response("잘못된 요청: token 누락", { status: 400, headers: H });

    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
    );

    const { data, error } = await supabase
      .from("subscribers")
      .update({ subscribed: false })
      .eq("token", token)
      .select("email")
      .single();

    if (error || !data) {
      return new Response("이미 처리되었거나 잘못된 링크입니다.", { headers: H });
    }

    return new Response(`구독취소 완료: ${data.email}`, { headers: H });
  } catch (e) {
    console.error(e);
    return new Response("서버 오류", { status: 500, headers: H });
  }
});
