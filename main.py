import os
import discord
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive
import random
import asyncio
import sqlite3
from datetime import datetime


token = os.environ['TOKEN_BOT_DISCORD']

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

duels = {}

# Connexion à la base de données pour les stats
conn = sqlite3.connect("des_stats.db")
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

# --- Check personnalisé pour rôle sleeping ---
def is_sleeping():
    async def predicate(interaction: discord.Interaction) -> bool:
        role = discord.utils.get(interaction.guild.roles, name="sleeping")
        return role in interaction.user.roles
    return app_commands.check(predicate)

class RejoindreView(discord.ui.View):
    def __init__(self, message_id, joueur1, montant):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.joueur1 = joueur1
        self.montant = montant

    @discord.ui.button(label="🎯 Rejoindre le duel", style=discord.ButtonStyle.green)
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
            if data["joueur1"].id == joueur2.id or (
                "joueur2" in data and data["joueur2"] and data["joueur2"].id == joueur2.id
            ):
                await interaction.response.send_message(
                    "❌ Tu participes déjà à un autre duel. Termine-le avant d’en rejoindre un autre.",
                    ephemeral=True
                )
                return

        duel_data["joueur2"] = joueur2
        self.rejoindre.disabled = True
        await interaction.response.defer()
        original_message = await interaction.channel.fetch_message(self.message_id)

        # Mettre à jour l'embed immédiatement après que le joueur 2 a rejoint
        player2_joined_embed = discord.Embed(
            title="🤝 Duel en attente de lancement...",
            description=(
                f"{self.joueur1.mention} et {joueur2.mention} sont prêts ! "
                f"Montant: **{self.montant:,}".replace(",", " ") + " kamas** 💰\n\n"
                f"Le tirage de dés va commencer dans un instant..."
            ),
            color=discord.Color.blue()
        )
        player2_joined_embed.set_footer(text="Préparation du tirage...")
        await original_message.edit(embed=player2_joined_embed, view=None)

        await asyncio.sleep(5)

        suspense_embed = discord.Embed(
            title="🎲 Le tirage de dés est en cours...",
            description="On croise les doigts 🤞🏻 !",
            color=discord.Color.greyple()
        )
        suspense_embed.set_image(url="https://media.giphy.com/media/l4FGnj7QY7I134t3y/giphy.gif")
        await original_message.edit(embed=suspense_embed, view=None)

        await asyncio.sleep(5)

        resultat1 = random.randint(1, 6)
        resultat2 = random.randint(1, 6)
        
        gagnant = None
        if resultat1 > resultat2:
            gagnant = self.joueur1
        elif resultat2 > resultat1:
            gagnant = joueur2
        else: # Égalité
            gagnant = None

        result_embed = discord.Embed(
            title="🎲 Résultat du Duel de Dés",
            description="Et le résultat est...",
            color=discord.Color.green() if gagnant else discord.Color.red() if not gagnant else discord.Color.gold()
        )

        result_embed.add_field(
            name=f"🎲 Jet de {self.joueur1.display_name}",
            value=f"Le dé de {self.joueur1.mention} est tombé sur : **{resultat1}**",
            inline=False
        )
        result_embed.add_field(
            name=f"🎲 Jet de {joueur2.display_name}",
            value=f"Le dé de {joueur2.mention} est tombé sur : **{resultat2}**",
            inline=False
        )

        if gagnant:
            result_embed.add_field(
                name="**🏆 Gagnant**",
                value=f"**{gagnant.mention} remporte {2 * self.montant:,}".replace(",", " ") + " kamas 💰**",
                inline=False
            )
        else:
            result_embed.add_field(
                name="**🤝 Égalité**",
                value=f"Aucun gagnant ! Les {self.montant:,}".replace(",", " ") + " kamas sont remboursés.",
                inline=False
            )

        result_embed.set_footer(text="🎲 Duel terminé • Bonne chance pour le prochain !")

        await original_message.edit(embed=result_embed, view=None)

        # Enregistrement du duel dans la base de données si un gagnant existe
        if gagnant:
            now = datetime.utcnow()
            try:
                c.execute("INSERT INTO paris (joueur1_id, joueur2_id, montant, gagnant_id, date) VALUES (?, ?, ?, ?, ?)",
                          (self.joueur1.id, joueur2.id, self.montant, gagnant.id, now))
                conn.commit()
            except Exception as e:
                print("Erreur insertion base:", e)

        duels.pop(self.message_id, None)


class PariView(discord.ui.View):
    def __init__(self, interaction, montant):
        super().__init__(timeout=None)
        self.interaction = interaction
        self.montant = montant

@bot.tree.command(name="statsall", description="Affiche les statistiques de tous les duels de dés.")
@is_sleeping()
async def statsall(interaction: discord.Interaction):
    # Vérifiez si la commande est utilisée dans le bon salon.
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

    stats.sort(key=lambda x: x[2], reverse=True)

    if not stats:
        await interaction.response.send_message("Aucune donnée statistique disponible.", ephemeral=True)
        return

    view = StatsView(interaction, stats)
    await interaction.response.send_message(embed=view.get_embed(), view=view)

# --- Commande /mystats : stats personnelles ---
@bot.tree.command(name="mystats", description="Affiche tes statistiques de duels de dés personnelles.")
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
            title="📊 Tes Statistiques de Dés",
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
        description="Voici un résumé de tes performances aux dés.",
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
        embed = discord.Embed(title="📊 Statistiques de dés", color=discord.Color.gold())
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
                f"🎲 **Misés** : `{mises:,}` kamas | "
                f"💰 **Gagnés** : `{kamas_gagnes:,}` kamas | "
                f"🎯 **Winrate** : `{winrate:.1f}%` (**{victoires}**/**{total_paris}**)\n"
            )
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

@bot.tree.command(name="sleeping", description="Lancer un duel de dés avec un montant.")
@is_sleeping()
@app_commands.describe(montant="Montant misé en kamas")
async def sleeping(interaction: discord.Interaction, montant: int):
    if interaction.channel.name != "duel-dés-sleeping":
        await interaction.response.send_message("❌ Tu dois utiliser cette commande dans le salon `#duel-dés-sleeping`.", ephemeral=True)
        return

    if montant <= 0:
        await interaction.response.send_message("❌ Le montant doit être supérieur à 0.", ephemeral=True)
        return

    for duel_data in duels.values():
        if duel_data["joueur1"].id == interaction.user.id or (
            "joueur2" in duel_data and duel_data["joueur2"] and duel_data["joueur2"].id == interaction.user.id
        ):
            await interaction.response.send_message(
                "❌ Tu participes déjà à un autre duel. Termine-le ou utilise `/quit` pour l'annuler.",
                ephemeral=True
            )
            return

    embed = discord.Embed(
        title="🎲 Nouveau Duel de Dés",
        description=f"{interaction.user.mention} veut lancer un duel pour **{montant:,}".replace(",", " ") + " kamas** 💰",
        color=discord.Color.gold()
    )
    embed.add_field(name="Attente", value="Clique sur le bouton pour rejoindre le duel !", inline=False)

    rejoindre_view = RejoindreView(message_id=None, joueur1=interaction.user, montant=montant)

    role = discord.utils.get(interaction.guild.roles, name="sleeping")
    message = await interaction.response.send_message(
        content=f"{role.mention} — Un nouveau duel est prêt !",
        embed=embed,
        view=rejoindre_view,
        allowed_mentions=discord.AllowedMentions(roles=True)
    )
    
    rejoindre_view.message_id = message.id

    duels[message.id] = {
        "joueur1": interaction.user,
        "montant": montant,
    }


@bot.tree.command(name="quit", description="Annule le duel en cours que tu as lancé.")
@is_sleeping()
async def quit_duel(interaction: discord.Interaction):
    # 1. Vérifier si la commande est dans le bon salon.
    if interaction.channel.name != "duel-dés-sleeping":
        await interaction.response.send_message("❌ Tu dois utiliser cette commande dans le salon `#duel-dés-sleeping`.", ephemeral=True)
        return

    # 2. Accuser réception de l'interaction pour éviter les erreurs.
    await interaction.response.defer(ephemeral=True)

    # 3. Trouver le duel à annuler.
    duel_a_annuler = None
    for message_id, duel_data in duels.items():
        if duel_data["joueur1"].id == interaction.user.id and "joueur2" not in duel_data:
            duel_a_annuler = message_id
            break

    if duel_a_annuler is None:
        await interaction.followup.send("❌ Tu n'as aucun duel en attente à annuler.", ephemeral=True)
        return

    # 4. Supprimer le duel de la liste des duels en cours.
    duels.pop(duel_a_annuler)

    # 5. Tenter de modifier le message original pour indiquer que le duel est annulé.
    try:
        channel = interaction.channel
        message = await channel.fetch_message(duel_a_annuler)
        if message:
            embed = message.embeds[0]
            embed.color = discord.Color.red()
            embed.title = "🎲 Nouveau Duel de Dés (Annulé)"
            embed.description = "⚠️ Ce duel a été annulé par son créateur."
            await message.edit(embed=embed, view=None)
        else:
             # Si le message n'existe plus, on ne fait rien
            pass
    except (discord.NotFound, discord.Forbidden):
        # Si le message n'existe plus ou que le bot n'a pas les permissions, on ne fait rien.
        pass

    # 6. Envoyer le message de confirmation final.
    await interaction.followup.send("✅ Ton duel a bien été annulé.", ephemeral=True)

@bot.event
async def on_ready():
    print(f"{bot.user} est prêt !")
    try:
        await bot.tree.sync()
        print("✅ Commandes synchronisées.")
    except Exception as e:
        print(f"Erreur : {e}")

keep_alive()
bot.run(token)
