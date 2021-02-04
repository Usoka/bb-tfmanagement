from redbot.core import commands
import discord
import json
import re
import asyncio
from os import path


DATA_DIR = 'data/boombeach'
MANAGEMENT_FILE = DATA_DIR+'/meta.json'
TFDATA_FILE = DATA_DIR+'/tfdata.json'

NICK_MAX_LENGTH = 32
MAX_WAIT_S = 20
CLEANUP_DELAY_S = 60

AFFIRMATIVE_REGEX = r'^y(?:es?|eah|up)?\.?$'


class TFManagement(commands.Cog):
	"""Custom cog for TF management"""

	def __init__(self, bot):
		self.bot = bot
		with open(MANAGEMENT_FILE, 'r') as f:
			self.meta = json.load(f)
			self.levels = self.meta["level"]
			self.tf_ranks = self.meta["tf_ranks"]

		if path.exists(TFDATA_FILE):
			#load from file
			with open(TFDATA_FILE, 'r') as f:
				self.tfs = json.load(f)
		else:
			#default to empty dict
			self.tfs = dict()


	@commands.command()
	@commands.guild_only()
	async def listtfs(self, ctx):
		"""Returns a list of all TFs"""

		await ctx.send('**Task Forces:**\n{}'.format('\n'.join(map(lambda tf: tf["name"], self.tfs.values()))))


	@commands.command()
	@commands.has_any_role(184854821537316865, 325093590378348544)
	@commands.guild_only()
	async def addtf(self, ctx, name, memberrole: discord.Role, leadrole: discord.Role, channel: discord.TextChannel):
		"""Adds a TF for addmember and listtfs"""

		newtf = {
			"name": name,
			"member_roles": [memberrole.id],
			"lead_ranks": ["officer", "coleader", "leader"],
			"lead_roles": [leadrole.id],
			"channel": channel.id
		}

		shorthand = name.lower().replace(' ', '')
		if shorthand in self.tfs:
			await ctx.send('A TF with the same or similar name already exists. Would you like to replace it?')
			resp = await self.bot.wait_for('message', timeout=MAX_WAIT_S, check=lambda m: (m.author == ctx.author and m.channel == ctx.channel))

			if resp and re.match(AFFIRMATIVE_REGEX, resp.content.lower()):
				msg = await ctx.send('Replacing {}...'.format(name))
				self._addtf(newtf)
				success = 'TF {} replaced.'.format(name)
				try:
					msg.edit(content=success)
				except discord.Forbidden:
					ctx.send(success)
			return

		self._addtf(newtf)
		await ctx.send('Added TF {}.'.format(name))


	def _addtf(self, tf):
		shorthand = tf["name"].lower().replace(' ', '')
		self.tfs[shorthand] = tf
		with open(TFDATA_FILE, 'w') as f:
			json.dump(self.tfs, f, indent='\t')



	@commands.command()
	@commands.guild_only()
	async def addmember(self, ctx, user: discord.Member, tfname, rank):
		"""Adds a given member to a given TF"""

		#check author (invoking user's) permission level
		level = max(self._getlevel(r.id) for r in ctx.author.roles)

		if level <= 0:
			await ctx.send('⚠ Insufficient permissions to use this command.', delete_after=CLEANUP_DELAY_S)
			await ctx.message.delete(delay=CLEANUP_DELAY_S)
			return

		#Prevent changing own roles
		if user.id == ctx.author.id:
			await ctx.send('⚠ Cannot add rank to self.', delete_after=CLEANUP_DELAY_S)
			await ctx.message.delete(delay=CLEANUP_DELAY_S)
			return


		#Process Task Force name
		tfn = tfname.lower().replace(' ', '') #get TF name, but as separate variable from input
		if tfn not in self.tfs.keys():
			await ctx.send('⚠ Unrecognised Task Force "{}". Use `{}listtfs` for a list of Task Forces.'.format(tfname, ctx.prefix), delete_after=CLEANUP_DELAY_S)
			await ctx.message.delete(delay=CLEANUP_DELAY_S)
			return
		tf = self.tfs[tfn] #get actual TF


		#Process rank
		rank = rank.lower()
		#Convert alias to actual
		if rank in self.meta["rank_aliases"]:
			rank = self.meta["rank_aliases"][rank]

		if rank not in self.tf_ranks:
			await ctx.send('⚠ Unknown rank "{}". Rank must be one of: {}.'.format(rank, ', '.join(self.tf_ranks.keys())), delete_after=CLEANUP_DELAY_S)
			await ctx.message.delete(delay=CLEANUP_DELAY_S)
			return


		guild = ctx.guild
		cleanup = [ctx.message] #List of messages to bulk-delete. Starting with original command invocation


		#Check permissions
		target_level = self._getlevel(self.tf_ranks[rank])
		if level <= target_level:
			viable_ranks = []
			for ra, ro in self.tf_ranks.items():
				if self._getlevel(ro) < level:
					viable_ranks.append(ra)
			max_rank = max(viable_ranks, key=lambda r: self._getlevel(self.tf_ranks[r]))
			
			msg = await ctx.send('You can only apply the following ranks: {}.\nWould you like to add **{}** instead, and notify the GOs to change it to **{}**?'.format(', '.join(viable_ranks), max_rank, rank))
			cleanup.append(msg)

			resp = await self.bot.wait_for('message', timeout=MAX_WAIT_S, check=lambda m: (m.author == ctx.author and m.channel == ctx.channel))
			if resp:
				cleanup.append(resp)
			if resp and re.match(AFFIRMATIVE_REGEX, resp.content.lower()):
				cleanup.append(await ctx.send('Adding **{}** rank to **{}**.'.format(max_rank, user)))
				channel = guild.get_channel(self.meta["approval_channel"])
				if isinstance(channel, discord.TextChannel):
					try:
						await channel.send('User **{}** (id: {}) requested rank **{}** for TF **{}** be added to user **{}** (id: {}).'.format(ctx.author, ctx.author.id, rank, tf["name"], user, user.id))
					except discord.Forbidden:
						cleanup.append(await ctx.send('⚠ Error notifying GOs.'))
				rank = max_rank
			else:
				cleanup.append(await ctx.send('Cancelling addmember.'))
				await self._cleanup(ctx.channel, cleanup)
				return


		roles = []
		#Get roles
		roles += [guild.get_role(r) for r in tf["member_roles"]]
		roles.append(guild.get_role(self.tf_ranks[rank]))
		if rank in tf["lead_ranks"]:
			roles += [guild.get_role(r) for r in tf["lead_roles"]]

		#Add roles
		try:
			await user.add_roles(*roles, reason="addmember invoked by {}".format(ctx.author))
		except discord.Forbidden:
			await ctx.send('⚠ Error adding roles to user. Aborting.', delete_after=CLEANUP_DELAY_S)
			await ctx.message.delete(delay=CLEANUP_DELAY_S)
			return


		#Construct nickname
		name_ext = ' | {}'.format(tf["name"])
		nick = user.nick if user.nick else user.name
		new_nick = nick.split("|")[0].strip() + name_ext
		#Attempt set nickname
		if len(new_nick) > NICK_MAX_LENGTH:
			cleanup.append(await ctx.send('Cannot change user\'s nickname. New nickname exceeds max length.'))
		else:
			try:
				await user.edit(nick=new_nick, reason="addmember invoked by {}".format(ctx.author))
			except discord.Forbidden:
				cleanup.append(await ctx.send('⚠ Error setting user nickname.'))


		#Notify user in channel
		channel = guild.get_channel(tf["channel"])
		if isinstance(channel, discord.TextChannel):
			cleanup.append(await channel.send('Welcome, {}, to {}!'.format(user.mention, tf["name"])))
		else:
			cleanup.append(await ctx.send('Cannot notify user. TF channel unknown or not a text channel.'))


		cleanup.append(await ctx.send('Successfully added **{}** to **{}** TF. With rank **{}**.'.format(user, tfname, rank)))

		#Cleanup on aisle 4
		await self._cleanup(ctx.channel, cleanup)


	def _getlevel(self, roleid):
		return self.levels.get(str(roleid), 0)

	async def _cleanup(self, channel, mess):
		notif = await channel.send('These messages will now self-destruct in {} seconds.'.format(CLEANUP_DELAY_S))
		mess.append(notif)

		await asyncio.sleep(CLEANUP_DELAY_S)
		await channel.delete_messages(mess)