# cogs/moderation.py

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, List
from datetime import datetime, timedelta
import logging
import asyncio

from utils.db_manager import DBManager
from utils.config import ConfigManager

logger = logging.getLogger("onWhisper.Moderation")


class ModerationCog(commands.Cog):
    """⚔️ Moderation commands for server management"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: DBManager = bot.db_manager
        self.config: ConfigManager = bot.config_manager

    async def _check_mod_permissions(self, interaction: discord.Interaction) -> bool:
        """Check if user has moderation permissions"""
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False
            
        # Check if user is admin or has manage server permission
        if interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild:
            return True
            
        # Check for mod role from config
        mod_enabled = await self.config.get(interaction.guild.id, "moderation_enabled", True)
        if not mod_enabled:
            return False
            
        return interaction.user.guild_permissions.kick_members or interaction.user.guild_permissions.ban_members

    async def _send_user_dm(self, user: discord.User, guild: discord.Guild, action: str, reason: str, moderator: discord.Member) -> bool:
        """Attempt to DM user about moderation action. Returns True if successful."""
        try:
            embed = discord.Embed(
                title=f"⚠️ {action.title()} from {guild.name}",
                color=discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Action", value=action.title(), inline=True)
            embed.add_field(name="Moderator", value=str(moderator), inline=True)
            embed.add_field(name="Reason", value=reason, inline=False)
            
            await user.send(embed=embed)
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    # 👥 Member Management Commands
    
    @app_commands.command(name="kick", description="Remove a member from the server")
    @app_commands.describe(member="Member to kick", reason="Reason for the kick")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        """Kicks a member from the server"""
        if not await self._check_mod_permissions(interaction):
            return await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
            
        if not interaction.guild.me.guild_permissions.kick_members:
            return await interaction.response.send_message("❌ I don't have permission to kick members!", ephemeral=True)
            
        if member.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("❌ I cannot kick this member (role hierarchy)!", ephemeral=True)
            
        try:
            # Send DM first
            dm_sent = await self._send_user_dm(member, interaction.guild, "kick", reason, interaction.user)
            
            # Kick the member
            await member.kick(reason=f"By {interaction.user}: {reason}")
            
            # Log to database
            await self.db.log_moderation_action(
                interaction.guild.id,
                member.id,
                "KICK",
                reason,
                interaction.user.id
            )
            
            logger.info(f"Kicked {member} from {interaction.guild} by {interaction.user}: {reason}")
            
            embed = discord.Embed(
                title="👢 Member Kicked",
                color=discord.Color.orange(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.add_field(name="DM Sent", value="✅ Yes" if dm_sent else "❌ No", inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to kick that user!", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in kick command: {e}", exc_info=True)
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)

    @app_commands.command(name="ban", description="Ban a member permanently from the server")
    @app_commands.describe(member="Member to ban", reason="Reason for the ban")
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        """Bans a member from the server"""
        if not await self._check_mod_permissions(interaction):
            return await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
            
        if not interaction.guild.me.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ I don't have permission to ban members!", ephemeral=True)
            
        if member.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("❌ I cannot ban this member (role hierarchy)!", ephemeral=True)
            
        try:
            # Send DM first
            dm_sent = await self._send_user_dm(member, interaction.guild, "ban", reason, interaction.user)
            
            # Ban the member
            await member.ban(reason=f"By {interaction.user}: {reason}")
            
            # Log to database
            await self.db.log_moderation_action(
                interaction.guild.id,
                member.id,
                "BAN",
                reason,
                interaction.user.id
            )
            
            logger.info(f"Banned {member} from {interaction.guild} by {interaction.user}: {reason}")
            
            embed = discord.Embed(
                title="🔨 Member Banned",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.add_field(name="DM Sent", value="✅ Yes" if dm_sent else "❌ No", inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to ban that user!", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in ban command: {e}", exc_info=True)
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)

    @app_commands.command(name="unban", description="Unban a user from the server")
    @app_commands.describe(user="User to unban (by ID or mention)")
    async def unban(self, interaction: discord.Interaction, user: discord.User):
        """Unbans a user from the server"""
        if not await self._check_mod_permissions(interaction):
            return await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
            
        if not interaction.guild.me.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ I don't have permission to unban members!", ephemeral=True)
            
        try:
            # Check if user is actually banned
            try:
                await interaction.guild.fetch_ban(user)
            except discord.NotFound:
                return await interaction.response.send_message("❌ This user is not banned!", ephemeral=True)
            
            # Unban the user
            await interaction.guild.unban(user, reason=f"By {interaction.user}")
            
            # Log to database
            await self.db.log_moderation_action(
                interaction.guild.id,
                user.id,
                "UNBAN",
                f"Unbanned by {interaction.user}",
                interaction.user.id
            )
            
            logger.info(f"Unbanned {user} from {interaction.guild} by {interaction.user}")
            
            embed = discord.Embed(
                title="✅ User Unbanned",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to unban users!", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in unban command: {e}", exc_info=True)
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)

    # 🔇 Mute & Timeout Commands
    
    @app_commands.command(name="mute", description="Timeout a member for a specified duration")
    @app_commands.describe(member="Member to timeout", duration="Duration in minutes (1-40320)", reason="Reason for the timeout")
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duration: int, reason: str = "No reason provided"):
        """Timeouts a member using Discord's built-in timeout system"""
        if not await self._check_mod_permissions(interaction):
            return await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
            
        if not interaction.guild.me.guild_permissions.moderate_members:
            return await interaction.response.send_message("❌ I don't have permission to timeout members!", ephemeral=True)
            
        if duration < 1 or duration > 40320:  # Discord's limit: 28 days
            return await interaction.response.send_message("❌ Duration must be between 1 minute and 28 days (40320 minutes)!", ephemeral=True)
            
        if member.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("❌ I cannot timeout this member (role hierarchy)!", ephemeral=True)
            
        try:
            until = datetime.utcnow() + timedelta(minutes=duration)
            await member.timeout(until, reason=f"By {interaction.user}: {reason}")
            
            # Log to database
            await self.db.log_moderation_action(
                interaction.guild.id,
                member.id,
                "MUTE",
                f"{reason} (Duration: {duration} minutes)",
                interaction.user.id
            )
            
            logger.info(f"Timed out {member} for {duration} minutes by {interaction.user}: {reason}")
            
            embed = discord.Embed(
                title="🔇 Member Muted",
                color=discord.Color.yellow(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
            embed.add_field(name="Duration", value=f"{duration} minutes", inline=False)
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
            embed.add_field(name="Reason", value=reason, inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to timeout that user!", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in mute command: {e}", exc_info=True)
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)

    @app_commands.command(name="unmute", description="Remove timeout from a member")
    @app_commands.describe(member="Member to unmute")
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        """Removes timeout from a member"""
        if not await self._check_mod_permissions(interaction):
            return await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
            
        if not interaction.guild.me.guild_permissions.moderate_members:
            return await interaction.response.send_message("❌ I don't have permission to remove timeouts!", ephemeral=True)
            
        if not member.is_timed_out():
            return await interaction.response.send_message("❌ This member is not timed out!", ephemeral=True)
            
        try:
            await member.timeout(None, reason=f"Unmuted by {interaction.user}")
            
            # Log to database
            await self.db.log_moderation_action(
                interaction.guild.id,
                member.id,
                "UNMUTE",
                f"Unmuted by {interaction.user}",
                interaction.user.id
            )
            
            logger.info(f"Unmuted {member} by {interaction.user}")
            
            embed = discord.Embed(
                title="🔊 Member Unmuted",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to unmute that user!", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in unmute command: {e}", exc_info=True)
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)

    # ⚠️ Warning Commands
    
    @app_commands.command(name="warn", description="Issue a warning to a member")
    @app_commands.describe(member="Member to warn", reason="Reason for the warning")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        """Issues a warning to a member"""
        if not await self._check_mod_permissions(interaction):
            return await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
            
        try:
            # Send DM first
            dm_sent = await self._send_user_dm(member, interaction.guild, "warning", reason, interaction.user)
            
            # Log to database
            await self.db.log_moderation_action(
                interaction.guild.id,
                member.id,
                "WARN",
                reason,
                interaction.user.id
            )
            
            logger.info(f"Warned {member} by {interaction.user}: {reason}")
            
            embed = discord.Embed(
                title="⚠️ Member Warned",
                color=discord.Color.gold(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=False)
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.add_field(name="DM Sent", value="✅ Yes" if dm_sent else "❌ No", inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in warn command: {e}", exc_info=True)
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)

    @app_commands.command(name="warnings", description="Display all warnings for a member")
    @app_commands.describe(member="Member to check warnings for")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        """Shows all warnings for a member"""
        if not await self._check_mod_permissions(interaction):
            return await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
            
        try:
            # Get warnings from database
            warnings = await self.db.get_moderation_logs(interaction.guild.id, member.id)
            warn_list = [log for log in warnings if log["action"] == "WARN"]
            
            if not warn_list:
                embed = discord.Embed(
                    title="📋 Member Warnings",
                    description=f"{member} has no warnings.",
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title="📋 Member Warnings",
                    description=f"{member} has {len(warn_list)} warning(s):",
                    color=discord.Color.orange()
                )
                
                for i, warning in enumerate(warn_list[:10], 1):  # Show up to 10 warnings
                    mod = interaction.guild.get_member(warning["moderator_id"])
                    mod_name = str(mod) if mod else f"ID: {warning['moderator_id']}"
                    
                    embed.add_field(
                        name=f"Warning #{warning['case_id']}",
                        value=f"**Reason:** {warning['reason']}\n**Moderator:** {mod_name}\n**Date:** {warning['timestamp']}",
                        inline=False
                    )
                
                if len(warn_list) > 10:
                    embed.add_field(name="Note", value=f"Showing 10 of {len(warn_list)} warnings.", inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in warnings command: {e}", exc_info=True)
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)

    # 📜 Moderation Logs
    
    @app_commands.command(name="modlogs", description="Display all moderation actions for a member")
    @app_commands.describe(member="Member to check moderation logs for")
    async def modlogs(self, interaction: discord.Interaction, member: discord.Member):
        """Shows all moderation actions for a member"""
        if not await self._check_mod_permissions(interaction):
            return await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
            
        try:
            # Get all moderation logs from database
            logs = await self.db.get_moderation_logs(interaction.guild.id, member.id)
            
            if not logs:
                embed = discord.Embed(
                    title="📜 Moderation Logs",
                    description=f"{member} has no moderation history.",
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title="📜 Moderation Logs",
                    description=f"{member} has {len(logs)} moderation action(s):",
                    color=discord.Color.blue()
                )
                
                for i, log in enumerate(logs[:10], 1):  # Show up to 10 logs
                    mod = interaction.guild.get_member(log["moderator_id"])
                    mod_name = str(mod) if mod else f"ID: {log['moderator_id']}"
                    
                    # Color code by action
                    action_emoji = {
                        "WARN": "⚠️",
                        "MUTE": "🔇", 
                        "UNMUTE": "🔊",
                        "KICK": "👢",
                        "BAN": "🔨",
                        "UNBAN": "✅",
                        "PURGE": "🧹",
                        "LOCK": "🔒",
                        "UNLOCK": "🔓"
                    }.get(log["action"], "📝")
                    
                    embed.add_field(
                        name=f"{action_emoji} Case #{log['case_id']} - {log['action']}",
                        value=f"**Reason:** {log['reason']}\n**Moderator:** {mod_name}\n**Date:** {log['timestamp']}",
                        inline=False
                    )
                
                if len(logs) > 10:
                    embed.add_field(name="Note", value=f"Showing 10 of {len(logs)} actions.", inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in modlogs command: {e}", exc_info=True)
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)

    # 🧹 Channel Management Commands
    
    @app_commands.command(name="purge", description="Bulk delete messages from the channel")
    @app_commands.describe(limit="Number of messages to delete (1-100)")
    async def purge(self, interaction: discord.Interaction, limit: int):
        """Bulk deletes messages from the current channel"""
        if not await self._check_mod_permissions(interaction):
            return await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
            
        if not interaction.guild.me.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ I don't have permission to delete messages!", ephemeral=True)
            
        if limit < 1 or limit > 100:
            return await interaction.response.send_message("❌ Please provide a number between 1 and 100.", ephemeral=True)
            
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("❌ This command can only be used in text channels!", ephemeral=True)
            
        try:
            await interaction.response.defer(ephemeral=True)
            
            deleted = await interaction.channel.purge(limit=limit)
            deleted_count = len(deleted)
            
            # Log the action
            await self.db.log_moderation_action(
                interaction.guild.id,
                interaction.user.id,
                "PURGE",
                f"Purged {deleted_count} messages in #{interaction.channel.name}",
                interaction.user.id
            )
            
            logger.info(f"Purged {deleted_count} messages in #{interaction.channel.name} by {interaction.user}")
            
            await interaction.followup.send(f"✨ Successfully deleted {deleted_count} message{'s' if deleted_count != 1 else ''}.", ephemeral=True)
            
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to delete messages!", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in purge command: {e}", exc_info=True)
            await interaction.followup.send("❌ An unexpected error occurred.", ephemeral=True)

    @app_commands.command(name="lock", description="Lock a channel to prevent @everyone from sending messages")
    @app_commands.describe(channel="Channel to lock (defaults to current channel)")
    async def lock(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        """Locks a channel to prevent @everyone from sending messages"""
        if not await self._check_mod_permissions(interaction):
            return await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
            
        if not interaction.guild.me.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ I don't have permission to manage channels!", ephemeral=True)
            
        channel = channel or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("❌ This command can only be used on text channels!", ephemeral=True)
            
        try:
            await channel.set_permissions(
                interaction.guild.default_role,
                send_messages=False,
                reason=f"Channel locked by {interaction.user}"
            )
            
            # Log the action
            await self.db.log_moderation_action(
                interaction.guild.id,
                interaction.user.id,
                "LOCK",
                f"Locked channel #{channel.name}",
                interaction.user.id
            )
            
            logger.info(f"Locked #{channel.name} by {interaction.user}")
            
            embed = discord.Embed(
                title="🔒 Channel Locked",
                description=f"{channel.mention} has been locked.",
                color=discord.Color.red()
            )
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to modify channel permissions!", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in lock command: {e}", exc_info=True)
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)

    @app_commands.command(name="unlock", description="Unlock a channel to restore @everyone sending messages")
    @app_commands.describe(channel="Channel to unlock (defaults to current channel)")
    async def unlock(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        """Unlocks a channel to restore @everyone sending messages"""
        if not await self._check_mod_permissions(interaction):
            return await interaction.response.send_message("❌ You don't have permission to use this command!", ephemeral=True)
            
        if not interaction.guild.me.guild_permissions.manage_channels:
            return await interaction.response.send_message("❌ I don't have permission to manage channels!", ephemeral=True)
            
        channel = channel or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("❌ This command can only be used on text channels!", ephemeral=True)
            
        try:
            await channel.set_permissions(
                interaction.guild.default_role,
                send_messages=None,  # Reset to default
                reason=f"Channel unlocked by {interaction.user}"
            )
            
            # Log the action
            await self.db.log_moderation_action(
                interaction.guild.id,
                interaction.user.id,
                "UNLOCK",
                f"Unlocked channel #{channel.name}",
                interaction.user.id
            )
            
            logger.info(f"Unlocked #{channel.name} by {interaction.user}")
            
            embed = discord.Embed(
                title="🔓 Channel Unlocked",
                description=f"{channel.mention} has been unlocked.",
                color=discord.Color.green()
            )
            embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to modify channel permissions!", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in unlock command: {e}", exc_info=True)
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)


async def setup(bot: commands.Bot):
    """Load the moderation cog"""
    await bot.add_cog(ModerationCog(bot))