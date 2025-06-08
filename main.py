import discord
from discord.ext import commands
from discord import app_commands, ui
import os
from dotenv import load_dotenv
from flask import Flask
from threading import Thread
import asyncio
from datetime import datetime, timedelta
import random

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DEV_ROLE_NAME = "Dev"
LOG_CHANNEL_NAME = "application-logs"

# Flask app for keep-alive
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    try:
        app.run(host='0.0.0.0', port=8080)
    except OSError:
        # If port 8080 is busy, try 8081
        app.run(host='0.0.0.0', port=8081)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Start the keep-alive server
keep_alive()

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Server-specific storage
server_data = {
    # guild_id: {
    #   'declined': {user_id: datetime},
    #   'banned': {user_id: {'reason': str, 'date': datetime}},
    #   'history': {user_id: list of application history}
    # }
}

# Global storage for cross-server reference
global_declined = {}  # user_id : datetime_of_decline
global_banned = {}     # user_id : {"reason": str, "date": datetime}
pending_applications = {}  # user_id: {"message_id": int, "role_type": str, "guild_id": int}

# Application questions
questions = {
    "Staff": [
        "1. Why do you want to be staff?",
        "2. What is your Roblox username?",
        "3. How would you handle a rule breaker?",
        "4. What timezone are you in?",
        "5. How many hours per week can you dedicate?",
        "6. Have you been staff elsewhere?",
        "7. How would you deal with a difficult member?",
        "8. What makes you stand out from other applicants?",
        "9. How would you improve our server?",
        "10. Any additional comments?"
    ],
    "Media": [
        "1. What kind of media do you create?",
        "2. Can we see examples of your work? (provide links)",
        "3. What software/tools do you use?",
        "4. How long have you been creating content?",
        "5. What's your strongest skill?",
        "6. What type of content do you want to create for us?",
        "7. Do you have experience with graphic design?",
        "8. Can you work with deadlines?",
        "9. What social media platforms are you active on?",
        "10. Any additional comments?"
    ],
    "Developer": [
        "1. What do you do?",
        "2. How long have you been developing on roblox?",
        "3. Do you have experience in working with a team?",
        "4. What's your Roblox username?",
        "5. Do you have a mic?",
        "6. Do you agree to Roblox's TOS?",
        "7. What development tools do you use?",
        "8. Describe your problem-solving approach",
        "9. Have you joined the roblox group?",
        "10. Any additional comments?"
    ]
}

application_status = {"Staff": True, "Media": True, "Developer": True}

class RoleSelect(ui.Select):
    def __init__(self, guild_id: int):
        options = []
        if application_status["Staff"]:
            options.append(discord.SelectOption(label="Staff", description="Apply for Staff role", emoji="🛡️"))
        if application_status["Media"]:
            options.append(discord.SelectOption(label="Media", description="Apply for Media role", emoji="🎥"))
        if application_status["Developer"]:
            options.append(discord.SelectOption(label="Developer", description="Apply for Developer role", emoji="💻"))

        super().__init__(
            placeholder="Select an application role...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        role_type = self.values[0]
        guild_id = interaction.guild.id

        # Initialize server data if not exists
        if guild_id not in server_data:
            server_data[guild_id] = {'declined': {}, 'banned': {}, 'history': {}}

        # Check global ban first
        if interaction.user.id in global_banned:
            ban_info = global_banned[interaction.user.id]
            await interaction.response.send_message(
                f"❌ You are globally banned from applying.\nReason: {ban_info['reason']}\nBanned on: {ban_info['date'].strftime('%Y-%m-%d %H:%M UTC')}",
                ephemeral=True
            )
            return

        # Check server-specific ban
        if interaction.user.id in server_data[guild_id]['banned']:
            ban_info = server_data[guild_id]['banned'][interaction.user.id]
            await interaction.response.send_message(
                f"❌ You are banned from applying in this server.\nReason: {ban_info['reason']}\nBanned on: {ban_info['date'].strftime('%Y-%m-%d %H:%M UTC')}",
                ephemeral=True
            )
            return

        # Check global decline cooldown (48h)
        last_decline = global_declined.get(interaction.user.id)
        if last_decline and datetime.utcnow() < last_decline + timedelta(hours=48):
            remaining = (last_decline + timedelta(hours=48)) - datetime.utcnow()
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            await interaction.response.send_message(
                f"❌ You were declined recently. You can reapply in {hours}h {minutes}m.",
                ephemeral=True
            )
            return

        # Check server-specific decline cooldown (24h)
        server_decline = server_data[guild_id]['declined'].get(interaction.user.id)
        if server_decline and datetime.utcnow() < server_decline + timedelta(hours=24):
            remaining = (server_decline + timedelta(hours=24)) - datetime.utcnow()
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            await interaction.response.send_message(
                f"❌ You were declined in this server recently. You can reapply here in {hours}h {minutes}m.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        try:
            embed = discord.Embed(
                title=f"{role_type} Application",
                description="Click below to begin your application.",
                color=discord.Color.blurple()
            )
            await interaction.user.send(embed=embed, view=StartApplicationView(role_type, guild_id))
            await interaction.followup.send("📩 Check your DMs to continue your application.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ I couldn't DM you. Please check your privacy settings.", ephemeral=True)

class ApplicationView(ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.add_item(RoleSelect(guild_id))

class ReasonModal(ui.Modal, title="Enter Reason"):
    def __init__(self, action: str, applicant: discord.User, role_type: str, interaction: discord.Interaction, message_id: int, guild_id: int):
        super().__init__()
        self.action = action  # 'accept' or 'decline'
        self.applicant = applicant
        self.role_type = role_type
        self.interaction = interaction
        self.message_id = message_id
        self.guild_id = guild_id

        self.reason = ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, required=True, max_length=300)
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        # Check if this application has already been processed
        if self.applicant.id in pending_applications and pending_applications[self.applicant.id].get("message_id") == self.message_id:
            reason_text = self.reason.value

            # Initialize server data if not exists
            if self.guild_id not in server_data:
                server_data[self.guild_id] = {'declined': {}, 'banned': {}, 'history': {}}

            # Notify applicant & mods
            if self.action == "accept":
                try:
                    await self.applicant.send(embed=discord.Embed(
                        title="✅ Application Accepted",
                        description=f"Your application for **{self.role_type}** has been accepted.\n\n**Reason:** {reason_text}",
                        color=discord.Color.green()
                    ))
                    await self.log_decision(interaction, "accepted", reason_text)
                    await interaction.response.send_message("✅ Applicant accepted and notified with reason.", ephemeral=True)
                except discord.Forbidden:
                    await interaction.response.send_message("✅ Accepted but couldn't DM the applicant.", ephemeral=True)
            elif self.action == "decline":
                # Add to both global and server-specific decline records
                global_declined[self.applicant.id] = datetime.utcnow()
                server_data[self.guild_id]['declined'][self.applicant.id] = datetime.utcnow()
                
                try:
                    await self.applicant.send(embed=discord.Embed(
                        title="❌ Application Declined",
                        description=(
                            f"Your application has been declined.\n\n**Reason:** {reason_text}\n"
                            "You can open a new application in the next 48 hours (globally) or 24 hours (in this server)."
                        ),
                        color=discord.Color.red()
                    ))
                    await self.log_decision(interaction, "declined", reason_text)
                    await interaction.response.send_message("❌ Applicant declined and notified with reason.", ephemeral=True)
                except discord.Forbidden:
                    await interaction.response.send_message("❌ Declined but couldn't DM the applicant.", ephemeral=True)
            
            # Remove from pending applications
            if self.applicant.id in pending_applications:
                pending_applications.pop(self.applicant.id)
        else:
            await interaction.response.send_message("⚠️ This application has already been processed.", ephemeral=True)

        self.stop()

    async def log_decision(self, interaction: discord.Interaction, action: str, reason: str = None):
        # Add to server history
        if self.applicant.id not in server_data[self.guild_id]['history']:
            server_data[self.guild_id]['history'][self.applicant.id] = []
        
        server_data[self.guild_id]['history'][self.applicant.id].append({
            "action": action,
            "role": self.role_type,
            "date": datetime.utcnow(),
            "moderator": interaction.user.name,
            "reason": reason
        })
        
        # Find the log channel
        log_channel = None
        guild = bot.get_guild(self.guild_id)
        if guild:
            log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
        
        if log_channel:
            embed = discord.Embed(
                title=f"Application {action.capitalize()}",
                color=discord.Color.green() if action == "accepted" else discord.Color.red()
            )
            embed.add_field(name="Applicant", value=f"{self.applicant} ({self.applicant.id})", inline=False)
            embed.add_field(name="Role", value=self.role_type, inline=False)
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)
            embed.timestamp = datetime.utcnow()
            
            await log_channel.send(embed=embed)

class ReviewView(ui.View):
    def __init__(self, applicant: discord.User, role_type: str, message_id: int, guild_id: int):
        super().__init__(timeout=None)
        self.applicant = applicant
        self.role_type = role_type
        self.message_id = message_id
        self.guild_id = guild_id
        self.processed = False

        # Initialize server data if not exists
        if self.guild_id not in server_data:
            server_data[self.guild_id] = {'declined': {}, 'banned': {}, 'history': {}}

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.processed or (self.applicant.id in pending_applications and pending_applications[self.applicant.id].get("message_id") != self.message_id):
            await interaction.response.send_message("⚠️ This application has already been processed.", ephemeral=True)
            return False
        return True

    async def log_decision(self, interaction: discord.Interaction, action: str, reason: str = None):
        # Add to server history
        if self.applicant.id not in server_data[self.guild_id]['history']:
            server_data[self.guild_id]['history'][self.applicant.id] = []
        
        server_data[self.guild_id]['history'][self.applicant.id].append({
            "action": action,
            "role": self.role_type,
            "date": datetime.utcnow(),
            "moderator": interaction.user.name,
            "reason": reason
        })
        
        # Add to global and server-specific data if declined
        if action == "declined":
            global_declined[self.applicant.id] = datetime.utcnow()
            server_data[self.guild_id]['declined'][self.applicant.id] = datetime.utcnow()
        
        # Find the log channel
        log_channel = None
        guild = bot.get_guild(self.guild_id)
        if guild:
            log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
        
        if log_channel:
            embed = discord.Embed(
                title=f"Application {action.capitalize()}",
                color=discord.Color.green() if action == "accepted" else discord.Color.red()
            )
            embed.add_field(name="Applicant", value=f"{self.applicant} ({self.applicant.id})", inline=False)
            embed.add_field(name="Role", value=self.role_type, inline=False)
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)
            embed.timestamp = datetime.utcnow()
            
            await log_channel.send(embed=embed)

    @ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.applicant.send(embed=discord.Embed(
                title="✅ Application Accepted",
                description=f"Congratulations! Your application for **{self.role_type}** has been accepted.",
                color=discord.Color.green()
            ))
            await self.log_decision(interaction, "accepted")
            await interaction.response.send_message("✅ Applicant accepted and notified.", ephemeral=True)
            self.processed = True
            if self.applicant.id in pending_applications:
                pending_applications.pop(self.applicant.id)
        except discord.Forbidden:
            await interaction.response.send_message("✅ Accepted but couldn't DM the applicant.", ephemeral=True)
        self.stop()

    @ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        global_declined[self.applicant.id] = datetime.utcnow()
        server_data[self.guild_id]['declined'][self.applicant.id] = datetime.utcnow()
        try:
            await self.applicant.send(embed=discord.Embed(
                title="❌ Application Declined",
                description=(
                    "Your application has been declined. "
                    "You can open a new application in the next 48 hours (globally) or 24 hours (in this server)."
                ),
                color=discord.Color.red()
            ))
            await self.log_decision(interaction, "declined")
            await interaction.response.send_message("❌ Applicant declined and notified.", ephemeral=True)
            self.processed = True
            if self.applicant.id in pending_applications:
                pending_applications.pop(self.applicant.id)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Declined but couldn't DM the applicant.", ephemeral=True)
        self.stop()

    @ui.button(label="Accept with Reason", style=discord.ButtonStyle.success, row=1)
    async def accept_reason(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ReasonModal("accept", self.applicant, self.role_type, interaction, self.message_id, self.guild_id)
        await interaction.response.send_modal(modal)

    @ui.button(label="Decline with Reason", style=discord.ButtonStyle.danger, row=1)
    async def decline_reason(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ReasonModal("decline", self.applicant, self.role_type, interaction, self.message_id, self.guild_id)
        await interaction.response.send_modal(modal)

class StartApplicationView(ui.View):
    def __init__(self, role_type: str, guild_id: int):
        super().__init__(timeout=None)
        self.role_type = role_type
        self.guild_id = guild_id

    @ui.button(label="Start Application", style=discord.ButtonStyle.primary)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Let's begin. Please answer the following questions in DM one by one.", ephemeral=True)

        qlist = questions[self.role_type]
        answers = []

        def check(m):
            return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)

        for q in qlist:
            await interaction.user.send(q)
            try:
                msg = await bot.wait_for('message', check=check, timeout=300)
                answers.append((q, msg.content))
            except asyncio.TimeoutError:
                await interaction.user.send("⏰ You took too long to answer. Application canceled.")
                return

        embed = discord.Embed(
            title=f"{interaction.user} Application for {self.role_type}",
            color=discord.Color.blue()
        )
        for q, a in answers:
            embed.add_field(name=q, value=a, inline=False)
        embed.set_footer(text=f"User ID: {interaction.user.id} | Guild ID: {self.guild_id}")

        sent = False
        guild = bot.get_guild(self.guild_id)
        if guild:
            channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
            if channel:
                try:
                    # Send @here ping before the embed
                    message = await channel.send("@here New application received!")
                    await channel.send(embed=embed, view=ReviewView(interaction.user, self.role_type, message.id, self.guild_id))
                    
                    # Track this pending application
                    pending_applications[interaction.user.id] = {
                        "message_id": message.id,
                        "role_type": self.role_type,
                        "guild_id": self.guild_id
                    }
                    
                    sent = True
                except Exception as e:
                    print(f"Failed to send application embed in channel: {e}")

                for member in guild.members:
                    if any(role.name == DEV_ROLE_NAME for role in member.roles):
                        try:
                            await member.send(f"📨 {interaction.user} just submitted a **{self.role_type}** application.")
                        except discord.Forbidden:
                            print(f"❌ Couldn't DM {member}")

        if sent:
            await interaction.user.send(embed=discord.Embed(
                title="✅ Application Submitted",
                description="Your application has been submitted. Thank you!",
                color=discord.Color.green()
            ))
        else:
            await interaction.user.send("⚠️ Could not send your application to the review channel. Please notify staff.")

@tree.command(name="application", description="Create an application menu")
@app_commands.checks.has_role(DEV_ROLE_NAME)
async def application(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Application System",
        description=(
            "Interested in joining the team? Use the dropdown below to apply for a role!\n"
            "We're currently looking for talented Developers and dedicated Staff members.\n"
            "If you're a content creator, our Media Rank is open as well!"
        ),
        color=discord.Color.teal()
    )
    await interaction.response.send_message(embed=embed, view=ApplicationView(interaction.guild.id))

@tree.command(name="application_open", description="Open applications for a specific role")
@app_commands.describe(role_type="Which application type to open")
@app_commands.choices(role_type=[
    app_commands.Choice(name="Staff", value="Staff"),
    app_commands.Choice(name="Media", value="Media"),
    app_commands.Choice(name="Developer", value="Developer")
])
@app_commands.checks.has_role(DEV_ROLE_NAME)
async def application_open(interaction: discord.Interaction, role_type: str):
    if role_type not in application_status:
        await interaction.response.send_message("❌ Invalid role type.", ephemeral=True)
        return

    if application_status[role_type]:
        await interaction.response.send_message(f"ℹ️ {role_type} applications are already open.", ephemeral=True)
    else:
        application_status[role_type] = True
        await interaction.response.send_message(f"✅ {role_type} applications are now open!", ephemeral=False)

@tree.command(name="application_close", description="Close applications for a specific role")
@app_commands.describe(role_type="Which application type to close")
@app_commands.choices(role_type=[
    app_commands.Choice(name="Staff", value="Staff"),
    app_commands.Choice(name="Media", value="Media"),
    app_commands.Choice(name="Developer", value="Developer")
])
@app_commands.checks.has_role(DEV_ROLE_NAME)
async def application_close(interaction: discord.Interaction, role_type: str):
    if role_type not in application_status:
        await interaction.response.send_message("❌ Invalid role type.", ephemeral=True)
        return

    if not application_status[role_type]:
        await interaction.response.send_message(f"ℹ️ {role_type} applications are already closed.", ephemeral=True)
    else:
        application_status[role_type] = False
        await interaction.response.send_message(f"⛔ {role_type} applications are now closed!", ephemeral=False)

@tree.command(name="applicationban", description="Ban a user from applying")
@app_commands.describe(
    user="User to ban",
    reason="Reason for ban",
    global_ban="Whether to ban globally (default: server only)"
)
@app_commands.checks.has_role(DEV_ROLE_NAME)
async def applicationban(interaction: discord.Interaction, user: discord.User, reason: str, global_ban: bool = False):
    ban_info = {"reason": reason, "date": datetime.utcnow()}
    
    if global_ban:
        global_banned[user.id] = ban_info
        await interaction.response.send_message(f"🔨 {user} has been globally banned from applying.\nReason: {reason}", ephemeral=False)
    else:
        guild_id = interaction.guild.id
        if guild_id not in server_data:
            server_data[guild_id] = {'declined': {}, 'banned': {}, 'history': {}}
        server_data[guild_id]['banned'][user.id] = ban_info
        await interaction.response.send_message(f"🔨 {user} has been banned from applying in this server.\nReason: {reason}", ephemeral=False)

@tree.command(name="applicationunban", description="Unban a user from applying")
@app_commands.describe(
    user="User to unban",
    global_unban="Whether to unban globally (default: server only)"
)
@app_commands.checks.has_role(DEV_ROLE_NAME)
async def applicationunban(interaction: discord.Interaction, user: discord.User, global_unban: bool = False):
    if global_unban:
        if user.id in global_banned:
            global_banned.pop(user.id)
            await interaction.response.send_message(f"✅ {user} has been globally unbanned and can now apply.", ephemeral=False)
        else:
            await interaction.response.send_message(f"❌ {user} is not globally banned.", ephemeral=True)
    else:
        guild_id = interaction.guild.id
        if guild_id in server_data and user.id in server_data[guild_id]['banned']:
            server_data[guild_id]['banned'].pop(user.id)
            await interaction.response.send_message(f"✅ {user} has been unbanned in this server and can now apply here.", ephemeral=False)
        else:
            await interaction.response.send_message(f"❌ {user} is not banned in this server.", ephemeral=True)

@tree.command(name="applicationbans", description="List all users banned from applying")
@app_commands.describe(show_global="Whether to show global bans (default: server only)")
@app_commands.checks.has_role(DEV_ROLE_NAME)
async def applicationbans(interaction: discord.Interaction, show_global: bool = False):
    guild_id = interaction.guild.id
    
    if not show_global and (guild_id not in server_data or not server_data[guild_id]['banned']):
        await interaction.response.send_message("There are no server-specific banned users.", ephemeral=True)
        return
    elif show_global and not global_banned:
        await interaction.response.send_message("There are no globally banned users.", ephemeral=True)
        return

    embed = discord.Embed(
        title="Global Ban List" if show_global else "Server Ban List",
        color=discord.Color.red()
    )
    
    ban_data = global_banned if show_global else server_data.get(guild_id, {}).get('banned', {})
    
    for user_id, info in ban_data.items():
        user = bot.get_user(user_id)
        username = user.name if user else f"User ID {user_id}"
        embed.add_field(
            name=username,
            value=f"Reason: {info['reason']}\nBanned on: {info['date'].strftime('%Y-%m-%d %H:%M UTC')}",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="applicationhistory", description="View a user's application history")
@app_commands.describe(
    user="The user to check history for",
    show_global="Whether to show global history (default: server only)"
)
@app_commands.checks.has_role(DEV_ROLE_NAME)
async def application_history_command(interaction: discord.Interaction, user: discord.User, show_global: bool = False):
    guild_id = interaction.guild.id
    
    # Initialize server data if not exists
    if guild_id not in server_data:
        server_data[guild_id] = {'declined': {}, 'banned': {}, 'history': {}}
    
    # Get the appropriate history
    if show_global:
        # Combine all server histories for this user
        all_history = []
        for gid, data in server_data.items():
            if user.id in data.get('history', {}):
                all_history.extend(data['history'][user.id])
        
        if not all_history:
            await interaction.response.send_message(f"ℹ️ No global application history found for {user.mention}.", ephemeral=True)
            return
        
        history_source = "Global"
        history_entries = sorted(all_history, key=lambda x: x['date'], reverse=True)
    else:
        if user.id not in server_data[guild_id]['history'] or not server_data[guild_id]['history'][user.id]:
            await interaction.response.send_message(f"ℹ️ No server-specific application history found for {user.mention}.", ephemeral=True)
            return
        
        history_source = "Server"
        history_entries = sorted(server_data[guild_id]['history'][user.id], key=lambda x: x['date'], reverse=True)
    
    embed = discord.Embed(
        title=f"{history_source} Application History for {user}",
        color=discord.Color.blue()
    )
    
    for entry in history_entries[:25]:  # Limit to 25 entries to avoid embed limits
        status = "✅ Accepted" if entry["action"] == "accepted" else "❌ Declined"
        embed.add_field(
            name=f"{entry['role']} - {entry['date'].strftime('%Y-%m-%d %H:%M')}",
            value=f"{status} by {entry['moderator']}" + (f"\nReason: {entry['reason']}" if entry.get("reason") else ""),
            inline=False
        )
    
    if len(history_entries) > 25:
        embed.set_footer(text=f"Showing 25 of {len(history_entries)} total entries")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@application.error
async def application_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ An error occurred: {error}", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

bot.run(TOKEN)
