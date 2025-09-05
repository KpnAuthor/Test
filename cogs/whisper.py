# cogs/whisper.py

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional, Dict, Union
import logging
from datetime import datetime

from utils.db_manager import DBManager
from utils.config import ConfigManager

logger = logging.getLogger("onWhisper.Whisper")


class WhisperCog(commands.Cog):
    """🤫 Private thread-based whisper system for anonymous communication"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: DBManager = bot.db_manager
        self.config: ConfigManager = bot.config_manager
        # Cache for active whisper threads
        self._active_whispers: Dict[int, Dict[int, int]] = {}  # guild_id -> {user_id: thread_id}

    async def _setup_whisper_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        """Create or get the whisper management channel"""
        try:
            # Get whisper channel from config
            whisper_channel_id = await self.config.get(guild.id, "whisper_channel")
            whisper_enabled = await self.config.get(guild.id, "whisper_enabled", True)

            # If channel already exists, return it
            if whisper_channel_id:
                channel = guild.get_channel(int(whisper_channel_id))
                if channel:
                    return channel

            # Create new channel with proper permissions
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild.me: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_channels=True,
                    manage_threads=True,
                    manage_messages=True
                )
            }

            # Add admin permissions for staff
            for member in guild.members:
                if member.guild_permissions.administrator:
                    overwrites[member] = discord.PermissionOverwrite(
                        read_messages=True,
                        send_messages=True,
                        manage_threads=True
                    )

            channel = await guild.create_text_channel(
                name="🤫-whispers",
                topic="Private communication channel - Staff only",
                overwrites=overwrites,
                reason="Whisper system setup"
            )

            # Update config with new channel
            await self.config.set(guild.id, "whisper_channel", str(channel.id))
            logger.info(f"Created whisper channel {channel.name} ({channel.id}) in guild {guild.name} ({guild.id})")

            return channel

        except Exception as e:
            logger.error(f"Error setting up whisper channel in guild {guild.id}: {e}")
            return None

    async def _create_whisper_thread(self, channel: discord.TextChannel, 
                                   user: discord.Member, reason: str) -> Optional[discord.Thread]:
        """Create a new whisper thread"""
        try:
            # Create thread with anonymous name
            thread = await channel.create_thread(
                name=f"Whisper-{user.id}",
                type=discord.ChannelType.private_thread,
                reason=f"Whisper thread for {user}"
            )

            # Create initial message with metadata
            embed = discord.Embed(
                title="New Whisper Thread",
                description=reason or "No reason provided",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="User", value=f"{user.mention} ({user.id})")
            embed.add_field(name="Created", value=discord.utils.format_dt(datetime.utcnow(), 'R'))

            await thread.send(embed=embed)

            # Store in database using existing whispers table
            await self.db.execute(
                "INSERT INTO whispers (guild_id, user_id, thread_id, created_at, is_open) VALUES (?, ?, ?, ?, ?)",
                (channel.guild.id, user.id, thread.id, datetime.utcnow(), 1)
            )
            
            logger.info(f"Created whisper thread {thread.id} for user {user.id} in guild {channel.guild.id}")

            # Update cache
            if channel.guild.id not in self._active_whispers:
                self._active_whispers[channel.guild.id] = {}
            self._active_whispers[channel.guild.id][user.id] = thread.id

            return thread

        except Exception as e:
            logger.error(f"Error creating whisper thread for user {user.id} in guild {channel.guild.id}: {e}")
            return None

    @app_commands.command(name="whisper")
    @app_commands.describe(reason="Reason for opening the whisper thread")
    async def create_whisper(self, interaction: discord.Interaction, reason: Optional[str] = None):
        """Open a private whisper thread for anonymous communication with staff"""
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used in a server!",
                ephemeral=True
            )

        try:
            # Check if whispers are enabled
            whisper_enabled = await self.config.get(interaction.guild.id, "whisper_enabled", True)
            if not whisper_enabled:
                return await interaction.response.send_message(
                    "❌ The whisper system is not enabled in this server.",
                    ephemeral=True
                )

            # Check if user already has an active whisper
            if (active_whispers := self._active_whispers.get(interaction.guild.id)) and \
               interaction.user.id in active_whispers:
                thread_id = active_whispers[interaction.user.id]
                return await interaction.response.send_message(
                    f"ℹ️ You already have an active whisper thread: <#{thread_id}>",
                    ephemeral=True
                )

            await interaction.response.defer(ephemeral=True)

            # Get or create whisper channel
            channel = await self._setup_whisper_channel(interaction.guild)
            if not channel:
                return await interaction.followup.send(
                    "❌ Failed to set up whisper channel. Please contact an administrator.",
                    ephemeral=True
                )

            # Create thread
            thread = await self._create_whisper_thread(channel, interaction.user, reason)
            if not thread:
                return await interaction.followup.send(
                    "❌ Failed to create whisper thread. Please try again later.",
                    ephemeral=True
                )

            await interaction.followup.send(
                f"✅ Whisper thread created: {thread.mention}\n" +
                "Staff will respond to your message soon.",
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error creating whisper for user {interaction.user.id} in guild {interaction.guild.id}: {e}")
            await interaction.followup.send(
                "❌ An error occurred while creating the whisper thread.",
                ephemeral=True
            )

    @app_commands.command(name="close")
    @app_commands.describe(reason="Reason for closing the whisper thread")
    async def close_whisper(self, interaction: discord.Interaction, reason: Optional[str] = None):
        """Close an active whisper thread"""
        if not interaction.guild or not isinstance(interaction.channel, discord.Thread):
            return await interaction.response.send_message(
                "This command can only be used in a whisper thread!",
                ephemeral=True
            )

        try:
            # Verify this is a whisper thread
            whisper = await self.db.fetchone(
                "SELECT user_id FROM whispers WHERE guild_id = ? AND thread_id = ? AND is_open = ?",
                (interaction.guild.id, interaction.channel.id, 1)
            )
            if not whisper:
                return await interaction.response.send_message(
                    "❌ This is not a whisper thread!",
                    ephemeral=True
                )

            # Check permissions (admins and thread creator can close)
            is_staff = interaction.user.guild_permissions.administrator

            if not (is_staff or interaction.user.id == whisper['user_id']):
                return await interaction.response.send_message(
                    "❌ You don't have permission to close this thread!",
                    ephemeral=True
                )

            # Send closing message
            embed = discord.Embed(
                title="Whisper Thread Closed",
                description=reason or "No reason provided",
                color=discord.Color.red(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Closed by", value=interaction.user.mention)
            await interaction.channel.send(embed=embed)

            # Update database
            await self.db.execute(
                "UPDATE whispers SET is_open = ?, closed_at = ? WHERE guild_id = ? AND thread_id = ?",
                (0, datetime.utcnow(), interaction.guild.id, interaction.channel.id)
            )
            
            logger.info(f"Closed whisper thread {interaction.channel.id} by {interaction.user.id} in guild {interaction.guild.id}")

            # Update cache
            if interaction.guild.id in self._active_whispers:
                self._active_whispers[interaction.guild.id].pop(whisper['user_id'], None)

            # Archive and lock the thread
            await interaction.channel.edit(archived=True, locked=True)

            await interaction.response.send_message(
                "✅ Whisper thread closed.",
                ephemeral=True
            )

        except Exception as e:
            logger.error(f"Error closing whisper thread {interaction.channel.id} in guild {interaction.guild.id}: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while closing the whisper thread.",
                ephemeral=True
            )

    @app_commands.command(name="whisper-setup")
    @app_commands.describe(
        enabled="Enable or disable the whisper system",
        channel="Channel for whisper threads (will create one if not specified)"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def setup_whispers(
        self,
        interaction: discord.Interaction,
        enabled: Optional[bool] = None,
        channel: Optional[discord.TextChannel] = None
    ):
        """Configure the whisper system"""
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used in a server!",
                ephemeral=True
            )

        try:
            # Update configuration
            if enabled is not None:
                await self.config.set(interaction.guild.id, "whisper_enabled", enabled)
                
            if channel:
                await self.config.set(interaction.guild.id, "whisper_channel", str(channel.id))

            # Get current settings for display
            whisper_enabled = await self.config.get(interaction.guild.id, "whisper_enabled", True)
            whisper_channel_id = await self.config.get(interaction.guild.id, "whisper_channel")
            
            # Create response embed
            embed = discord.Embed(
                title="⚙️ Whisper System Settings",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )

            embed.add_field(
                name="Status",
                value="✅ Enabled" if whisper_enabled else "❌ Disabled",
                inline=True
            )

            if whisper_channel_id:
                embed.add_field(
                    name="Whisper Channel",
                    value=f"<#{whisper_channel_id}>",
                    inline=True
                )
                
            embed.add_field(
                name="Usage",
                value="Use `/whisper` to create a private thread",
                inline=False
            )

            await interaction.response.send_message(embed=embed)

            # Setup channel if enabled and no channel specified
            if enabled and not whisper_channel_id:
                await self._setup_whisper_channel(interaction.guild)
                
            logger.info(f"Updated whisper settings in guild {interaction.guild.id} by {interaction.user.id}")

        except Exception as e:
            logger.error(f"Error updating whisper settings in guild {interaction.guild.id}: {e}")
            await interaction.response.send_message(
                f"❌ An error occurred while updating settings: {str(e)}",
                ephemeral=True
            )

    @app_commands.command(name="list-whispers")
    @app_commands.default_permissions(manage_guild=True)
    async def list_whispers(self, interaction: discord.Interaction):
        """List all active whisper threads"""
        if not interaction.guild:
            return await interaction.response.send_message(
                "This command can only be used in a server!",
                ephemeral=True
            )

        try:
            # Check permissions
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message(
                    "❌ You don't have permission to view whisper threads!",
                    ephemeral=True
                )

            # Get active whispers
            whispers = await self.db.fetchall(
                "SELECT user_id, thread_id, created_at FROM whispers WHERE guild_id = ? AND is_open = ?",
                (interaction.guild.id, 1)
            )
            if not whispers:
                return await interaction.response.send_message(
                    "ℹ️ No active whisper threads.",
                    ephemeral=True
                )

            # Create embed
            embed = discord.Embed(
                title="📝 Active Whisper Threads",
                color=discord.Color.blue(),
                timestamp=datetime.utcnow()
            )

            for whisper in whispers:
                user = interaction.guild.get_member(whisper['user_id'])
                thread = interaction.guild.get_thread(whisper['thread_id'])

                if user and thread:
                    embed.add_field(
                        name=f"Thread: {thread.name}",
                        value=f"User: {user.mention}\n" +
                              f"Link: {thread.mention}\n" +
                              f"Created: {discord.utils.format_dt(whisper['created_at'], 'R')}",
                        inline=False
                    )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error listing whispers in guild {interaction.guild.id}: {e}")
            await interaction.response.send_message(
                "❌ An error occurred while fetching whisper threads.",
                ephemeral=True
            )

    async def cog_load(self):
        """Load active whispers into cache on startup"""
        for guild in self.bot.guilds:
            try:
                whispers = await self.db.fetchall(
                    "SELECT user_id, thread_id FROM whispers WHERE guild_id = ? AND is_open = ?",
                    (guild.id, 1)
                )
                if whispers:
                    self._active_whispers[guild.id] = {
                        w['user_id']: w['thread_id'] for w in whispers
                    }
                    logger.info(f"Loaded {len(whispers)} active whispers for guild {guild.id}")
            except Exception as e:
                logger.error(f"Error loading whispers for guild {guild.id}: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(WhisperCog(bot))