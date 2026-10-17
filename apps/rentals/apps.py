from django.apps import AppConfig


class RentalsConfig(AppConfig):
    name = "apps.rentals"
    verbose_name = "Pronájmy"

    def ready(self) -> None:
        from django.db.models.signals import post_delete

        from apps.rentals.models import Attachment
        from apps.rentals.services.attachments import delete_file

        def remove_file(sender: type[Attachment], instance: Attachment, **kwargs: object) -> None:
            # I při kaskádovém smazání (smlouva, oprava…) zmizí soubor z úložiště.
            delete_file(instance)

        post_delete.connect(remove_file, sender=Attachment, weak=False)
