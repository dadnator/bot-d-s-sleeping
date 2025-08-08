import os
import discord
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive
import random
import asyncio
import sqlite3
from datetime import datetime

# --- TOKEN ET INTENTS ---
token = os.environ['TOKEN_BOT_DISCORD']
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

duels = {}

# --- CONNEXION À LA BASE DE DONNÉES ---
conn = sqlite3.connect("dice_stats.db")
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS paris (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    joueur1_id INTEGER NOT NULL,
    joueur2_id INTEGER NOT NULL,
    montant INTEGER NOT NULL,
    gagnant_id INTEGER NOT NULL,
    date TIMESTAMP NOT NULL
)
""")
conn.commit()

# --- CHECK ROLE SLEEPING ---
def is_sleeping():
    async def predicate(interaction: discord.Interaction) -> bool:
        role = discord.utils.get(interaction.guild.roles, name="sleeping")
        return role in interaction.user.roles
    return app_commands.check(predicate)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)

class DuelView(discord.ui.View):
    def __init__(self, message_id, joueur1, montant):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.joueur1 = joueur1
        self.montant = montant

    @discord.ui.button(label="🎲 Rejoindre le duel", style=discord.ButtonStyle.green)
    async def rejoindre(self, interaction: discord.Interaction, button: discord.ui.Button):
        joueur2 = interaction.user

        if joueur2.id == self.joueur1.id:
            await interaction.response.send_message("❌ Tu ne peux pas rejoindre ton propre duel.", ephemeral=True)
            return

        duel_data = duels.get(self.message_id)
        if duel_data is None:
            await interaction.response.send_message("❌ Ce duel n'existe plus ou a déjà été joué.", ephemeral=True)
            return

        for data in duels.values():
            if data["joueur1"].id == joueur2.id or ("joueur2" in data and data["joueur2"] and data["joueur2"].id == joueur2.id):
                await interaction.response.send_message("❌ Tu participes déjà à un autre duel.", ephemeral=True)
                return

        duel_data["joueur2"] = joueur2
        self.rejoindre.disabled = True
        await interaction.response.defer()
        original_message = await interaction.channel.fetch_message(self.message_id)

        embed = discord.Embed(title="🎲 Duel de Dés !", description="Les joueurs sont prêts... Le duel commence !", color=discord.Color.blurple())
        embed.add_field(name="👤 Joueur 1", value=f"{self.joueur1.mention}", inline=True)
        embed.add_field(name="👤 Joueur 2", value=f"{joueur2.mention}", inline=True)
        await original_message.edit(embed=embed, view=None)

        # Animation de suspense pendant 10 secondes
        suspense = discord.Embed(title="🎲 Lancer des dés en cours...", description="Les dés sont jetés... 🎲", color=discord.Color.greyple())
        suspense.set_image(url="https://images.emojiterra.com/google/noto-emoji/animated-emoji/1f3b2.gif")
        await original_message.edit(embed=suspense)

        for i in range(10, 0, -1):
            suspense.title = f"🎲 Tirage en cours..."
            await original_message.edit(embed=suspense)
            await asyncio.sleep(1)


        # Lancer les dés après le suspense
        roll1 = random.randint(1, 6)
        roll2 = random.randint(1, 6)

        if roll1 > roll2:
            gagnant = self.joueur1
        elif roll2 > roll1:
            gagnant = joueur2
        else:
            gagnant = None

        # Embed du résultat
        result = discord.Embed(title="🎲 Résultat du Duel", color=discord.Color.green())
        result.add_field(name=f"{self.joueur1.display_name}", value=f"a lancé : **{roll1}**", inline=True)
        result.add_field(name=f"{joueur2.display_name}", value=f"a lancé : **{roll2}**", inline=True)
        result.add_field(name=" ", value="─" * 20, inline=False)
        result.add_field(name="💰 Montant misé", value=f"**{self.montant:,.0f}** kamas par joueur", inline=False)

        if gagnant:
            result.add_field(name="🏆 Gagnant", value=f"{gagnant.mention} remporte **{2 * self.montant:,.0f}** kamas !", inline=False)
        else:
            result.add_field(name="⚖️ Égalité", value="Aucun gagnant, vous récupérez vos mises", inline=False)

        # ⚠️ Met à jour d’abord le message avec l’embed final
        await original_message.edit(embed=result, view=None)

        # 🔔 Ensuite, annonce à part la fin du duel (ping)
       # Juste avant ça :
        role_sleeping = discord.utils.get(interaction.guild.roles, name="sleeping")

        # Et ici tu mets à jour le message AVEC le contenu + embed
        await original_message.edit(
            content=f"{role_sleeping.mention} — Le duel est terminé ! Voici les résultats 👇",
            embed=result,
            view=None
        )

        duels.pop(self.message_id, None)

        now = datetime.utcnow()
        try:
            if gagnant:
                c.execute("INSERT INTO paris (joueur1_id, joueur2_id, montant, gagnant_id, date) VALUES (?, ?, ?, ?, ?)",
                          (self.joueur1.id, joueur2.id, self.montant, gagnant.id, now))
                conn.commit()
        except Exception as e:
            print("Erreur base de données:", e)

# Tu peux ajouter ici les autres commandes : /sleeping, /quit, /mystats, /statsall comme dans ton ancien bot.

# Pagination pour affichage stats
class StatsView(discord.ui.View):
    def __init__(self, ctx, entries, page=0):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.entries = entries
        self.page = page
        self.entries_per_page = 10
        self.max_page = (len(entries) - 1) // self.entries_per_page

        self.update_buttons()

    def update_buttons(self):
        self.first_page.disabled = self.page == 0
        self.prev_page.disabled = self.page == 0
        self.next_page.disabled = self.page == self.max_page
        self.last_page.disabled = self.page == self.max_page

    def get_embed(self):
        embed = discord.Embed(title="📊 Statistiques duel de dés", color=discord.Color.gold())
        start = self.page * self.entries_per_page
        end = start + self.entries_per_page
        slice_entries = self.entries[start:end]

        if not slice_entries:
            embed.description = "Aucune donnée à afficher."
            return embed

        description = ""
        for i, (user_id, mises, kamas_gagnes, victoires, winrate, total_paris) in enumerate(slice_entries):
            rank = self.page * self.entries_per_page + i + 1
            description += (
                f"**#{rank}** <@{user_id}> — "
                f"<:emoji_2:1399792098529509546> **Misés** : **`{mises:,.0f}`".replace(",", " ") + " kamas** | "
                f"<:emoji_2:1399792098529509546> **Gagnés** : **`{kamas_gagnes:,.0f}`".replace(",", " ") + " kamas** | "
                f"**🎯Winrate** : **`{winrate:.1f}%`** (**{victoires}**/**{total_paris}**)\n"
            )
            # Ajoute une ligne de séparation après chaque joueur sauf le dernier de la page
            if i < len(slice_entries) - 1:
                description += "─" * 20 + "\n"

        embed.description = description
        embed.set_footer(text=f"Page {self.page + 1}/{self.max_page + 1}")
        return embed


    @discord.ui.button(label="⏮️", style=discord.ButtonStyle.secondary)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.max_page:
            self.page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = self.max_page
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

# --- Commande /statsall : stats à vie ---
@bot.tree.command(name="statsall", description="Affiche les stats du duel de dés ")
@is_sleeping()
async def statsall(interaction: discord.Interaction):
    # Vérifie si la commande est utilisée dans le bon salon.
    if not isinstance(interaction.channel, discord.TextChannel) or interaction.channel.name != "duel-dés-sleeping":
        await interaction.response.send_message(
            "❌ Cette commande ne peut être utilisée que dans le salon #duel-dés-sleeping.",
            ephemeral=True
        )
        return

    c.execute("""
    SELECT joueur_id,
           SUM(montant) as total_mise,
           SUM(CASE WHEN gagnant_id = joueur_id THEN montant * 2 ELSE 0 END) as kamas_gagnes,
           SUM(CASE WHEN gagnant_id = joueur_id THEN 1 ELSE 0 END) as victoires,
           COUNT(*) as total_paris
    FROM (
        SELECT joueur1_id as joueur_id, montant, gagnant_id FROM paris
        UNION ALL
        SELECT joueur2_id as joueur_id, montant, gagnant_id FROM paris
    )
    GROUP BY joueur_id
    """)
    data = c.fetchall()

    stats = []
    for user_id, mises, kamas_gagnes, victoires, total_paris in data:
        winrate = (victoires / total_paris * 100) if total_paris > 0 else 0.0
        stats.append((user_id, mises, kamas_gagnes, victoires, winrate, total_paris))

    # Tri par kamas gagnés
    stats.sort(key=lambda x: x[2], reverse=True)

    if not stats:
        await interaction.response.send_message("Aucune donnée statistique disponible.", ephemeral=True)
        return

    view = StatsView(interaction, stats)
    await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=False)

# --- Commande /mystats : stats personnelles ---
@bot.tree.command(name="mystats", description="Affiche tes statistiques du duel de dés personnelles.")
@is_sleeping()
async def mystats(interaction: discord.Interaction):
    # Récupère l'ID de l'utilisateur qui a lancé la commande
    user_id = interaction.user.id

    # Exécute une requête SQL pour obtenir les stats de l'utilisateur
    c.execute("""
    SELECT joueur_id,
           SUM(montant) as total_mise,
           SUM(CASE WHEN gagnant_id = joueur_id THEN montant * 2 ELSE 0 END) as kamas_gagnes,
           SUM(CASE WHEN gagnant_id = joueur_id THEN 1 ELSE 0 END) as victoires,
           COUNT(*) as total_paris
    FROM (
        SELECT joueur1_id as joueur_id, montant, gagnant_id FROM paris
        UNION ALL
        SELECT joueur2_id as joueur_id, montant, gagnant_id FROM paris
    )
    WHERE joueur_id = ?
    GROUP BY joueur_id
    """, (user_id,))
    
    # Récupère le résultat de la requête
    stats_data = c.fetchone()

    # Si aucune donnée n'est trouvée pour l'utilisateur
    if not stats_data:
        embed = discord.Embed(
            title="📊 Tes Statistiques duel de dés",
            description="❌ Tu n'as pas encore participé à un duel. Joue ton premier duel pour voir tes stats !",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Extrait les données de la requête
    _, mises, kamas_gagnes, victoires, total_paris = stats_data
    winrate = (victoires / total_paris * 100) if total_paris > 0 else 0.0

    # Crée un embed pour afficher les statistiques
    embed = discord.Embed(
        title=f"📊 Statistiques de {interaction.user.display_name}",
        description="Voici un résumé de tes performances au duel de dés.",
        color=discord.Color.gold()
    )

    # Ajoute les champs avec les statistiques
    embed.add_field(name="Total misé", value=f"**{mises:,.0f}".replace(",", " ") + " kamas**", inline=False)
    embed.add_field(name=" ", value="─" * 3, inline=False)
    embed.add_field(name="Total gagné", value=f"**{kamas_gagnes:,.0f}".replace(",", " ") + " kamas**", inline=False)
    embed.add_field(name=" ", value="─" * 20, inline=False)
    embed.add_field(name="Duels joués", value=f"**{total_paris}**", inline=True)
    embed.add_field(name=" ", value="─" * 3, inline=False)
    embed.add_field(name="Victoires", value=f"**{victoires}**", inline=True)
    embed.add_field(name=" ", value="─" * 3, inline=False)
    embed.add_field(name="Taux de victoire", value=f"**{winrate:.1f}%**", inline=False)

    embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else None)
    embed.set_footer(text="Bonne chance pour tes prochains duels !")

    await interaction.response.send_message(embed=embed, ephemeral=True)



# Commande /sleeping accessible uniquement aux membres avec rôle 'sleeping'
@bot.tree.command(name="sleeping", description="Lancer un duel de dés avec un montant.")
@is_sleeping()
@app_commands.describe(montant="Montant misé en kamas")
async def sleeping(interaction: discord.Interaction, montant: int):
    if interaction.channel.name != "duel-dés-sleeping":
        await interaction.response.send_message(
            "❌ Tu dois utiliser cette commande dans le salon `#duel-dés-sleeping`.", ephemeral=True)
        return

    if montant <= 0:
        await interaction.response.send_message("❌ Le montant doit être supérieur à 0.", ephemeral=True)
        return

    for duel_data in duels.values():
        if duel_data["joueur1"].id == interaction.user.id or (
            "joueur2" in duel_data and duel_data["joueur2"] and duel_data["joueur2"].id == interaction.user.id):
            await interaction.response.send_message(
                "❌ Tu participes déjà à un autre duel. Termine-le ou utilise `/quit` pour l'annuler.",
                ephemeral=True)
            return

    embed = discord.Embed(
        title="🎰 Nouveau Duel De Dés",
        description=f"{interaction.user.mention} lance un duel pour **{montant:,.0f}".replace(",", " ") + " kamas** 💰\n"
                    "Clique sur le bouton ci-dessous pour rejoindre !",
        color=discord.Color.gold()
    )

    # On crée une instance de DuelView sans message_id pour le moment
    view = DuelView(None, interaction.user, montant)

    # Envoi le message avec la vue contenant le bouton "Rejoindre le duel"
    role_sleeping = discord.utils.get(interaction.guild.roles, name="sleeping")
    await interaction.response.send_message(
    content=f"{role_sleeping.mention} — Un nouveau duel est prêt !",
    embed=embed,
    view=view,
    ephemeral=False,
    allowed_mentions=discord.AllowedMentions(roles=True)
)

    sent_message = await interaction.original_response()

    # Maintenant qu'on a le message_id, on l'affecte à la vue et au dict des duels
    view.message_id = sent_message.id
    duels[sent_message.id] = {"joueur1": interaction.user, "montant": montant, "joueur2": None}

    # Mise à jour du message pour que la vue contienne le bon message_id
    await sent_message.edit(view=view)


# Commande /quit accessible uniquement aux membres avec rôle 'sleeping'
@bot.tree.command(name="quit", description="Annule le duel en cours que tu as lancé.")
@is_sleeping()
async def quit_duel(interaction: discord.Interaction):
    if interaction.channel.name != "duel-dés-sleeping":
        await interaction.response.send_message(
            "❌ Tu dois utiliser cette commande dans le salon `#duel-dés-sleeping`.",
            ephemeral=True)
        return

    duel_a_annuler = None
    for message_id, duel_data in duels.items():
        if duel_data["joueur1"].id == interaction.user.id:
            duel_a_annuler = message_id
            break

    if duel_a_annuler is None:
        await interaction.response.send_message(
            "❌ Tu n'as aucun duel en attente à annuler.", ephemeral=True)
        return

    # Supprime le duel de la mémoire
    duels.pop(duel_a_annuler)

    # Essayer de modifier le message pour indiquer que le duel est annulé (optionnel)
    try:
        channel = interaction.channel
        message = await channel.fetch_message(duel_a_annuler)
        embed = discord.Embed(
            title="❌ Duel annulé",
            description=f"{interaction.user.mention} a annulé son duel.",
            color=discord.Color.red()
        )
        await message.edit(embed=embed, view=None)
    except Exception:
        # En cas d'erreur (message supprimé ou autre), on continue silencieusement
        pass

    await interaction.response.send_message(
        "✅ Ton duel a bien été annulé.", ephemeral=True)


# --- ACTIVER LE BOT ---
keep_alive()
bot.run(token)
